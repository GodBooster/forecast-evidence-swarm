//! Minimal escrow for synthetic forecast delivery jobs.
//!
//! The contract records acceptance and transfers only the fixed reward. It does not inspect
//! evidence, judge forecasts, or authenticate artifact contents. A digest binds bytes only.
//!
//! v2: every job binds the customer's order (`order_sha256`, the off-chain commitment of
//! the order terms), pays a fixed non-refundable storage deposit for its own permanent
//! record, emits NEP-297 events, and records the customer's publication consent on chain.

use near_sdk::serde_json::{json, Value};
use near_sdk::store::LookupMap;
use near_sdk::{env, near, require, AccountId, Gas, NearToken, PanicOnDefault, Promise, PromiseResult};

/// Contract-level reserve attached to `new`; never paid out.
const MIN_STORAGE_RESERVE: NearToken = NearToken::from_near(1);
/// Non-refundable part of every `create_job` deposit. It stakes the job's permanent
/// record. The worst-case record (64-character customer and worker IDs, order and
/// artifact hashes, all options set) is 390 bytes = 0.0039 NEAR at the protocol's
/// 10^19 yoctoNEAR/byte; 0.01 NEAR leaves a 2.56x margin (asserted in unit tests).
const JOB_STORAGE_DEPOSIT: NearToken = NearToken::from_millinear(10);
/// Static gas for `on_transfer_complete`. The local sandbox run measures the gas burnt by
/// every callback receipt and asserts that this allowance is at least twice the maximum.
const CALLBACK_GAS: Gas = Gas::from_tgas(10);
const EVENT_STANDARD: &str = "forecast_jobs";
const EVENT_VERSION: &str = "1.0.0";

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct ForecastJobs {
    resolver: AccountId,
    // Contract-level, non-withdrawable operating/storage reserve funded at initialization.
    storage_reserve: NearToken,
    // Sum of the non-refundable per-job storage deposits received; never paid out.
    storage_deposits: NearToken,
    // Rewards whose transfer has not been confirmed successful.
    escrowed_rewards: NearToken,
    jobs: LookupMap<u64, Job>,
    next_job_id: u64,
}

#[near(serializers = [borsh])]
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum JobStatus {
    Open,
    Assigned,
    Submitted,
    Disputed,
    PayoutPending,
    PayoutReady,
    RefundPending,
    RefundReady,
    Accepted,
    Refunded,
}

#[near(serializers = [borsh])]
pub struct Job {
    customer: AccountId,
    worker: Option<AccountId>,
    reward: NearToken,
    order_sha256: String,
    decision_deadline_ms: u64,
    delivery_deadline_ms: u64,
    acceptance_deadline_ms: u64,
    dispute_deadline_ms: u64,
    artifact_sha256: Option<String>,
    status: JobStatus,
    attempt_counter: u64,
    pending_attempt_id: Option<u64>,
    publication_consent: bool,
}

#[near(serializers = [json])]
pub struct JobView {
    pub id: u64,
    pub customer: AccountId,
    pub worker: Option<AccountId>,
    pub reward: NearToken,
    pub order_sha256: String,
    pub decision_deadline_ms: u64,
    pub delivery_deadline_ms: u64,
    pub acceptance_deadline_ms: u64,
    pub dispute_deadline_ms: u64,
    pub artifact_sha256: Option<String>,
    pub status: String,
    pub pending_attempt_id: Option<u64>,
    pub publication_consent: bool,
}

#[near(serializers = [json])]
pub struct ConfigView {
    pub resolver: AccountId,
    pub storage_reserve: NearToken,
    pub job_storage_deposit: NearToken,
    pub storage_deposits: NearToken,
    pub escrowed_rewards: NearToken,
    pub callback_gas: Gas,
    pub job_count: u64,
    pub event_standard: String,
    pub event_version: String,
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn add(a: NearToken, b: NearToken) -> NearToken {
    NearToken::from_yoctonear(a.as_yoctonear().checked_add(b.as_yoctonear()).expect("accounting overflow"))
}

/// NEP-297 event log. All numbers that can exceed 2^53 are strings.
fn emit(event: &str, data: Value) {
    let payload = json!({
        "standard": EVENT_STANDARD,
        "version": EVENT_VERSION,
        "event": event,
        "data": [data],
    });
    env::log_str(&format!("EVENT_JSON:{payload}"));
}

impl JobStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::Open => "OPEN",
            Self::Assigned => "ASSIGNED",
            Self::Submitted => "SUBMITTED",
            Self::Disputed => "DISPUTED",
            Self::PayoutPending => "PAYOUT_PENDING",
            Self::PayoutReady => "PAYOUT_READY",
            Self::RefundPending => "REFUND_PENDING",
            Self::RefundReady => "REFUND_READY",
            Self::Accepted => "ACCEPTED",
            Self::Refunded => "REFUNDED",
        }
    }
}

#[near]
impl ForecastJobs {
    /// Initialize with a named resolver. The attached deposit becomes a fixed reserve for
    /// contract operation/storage; it is not job budget and has no withdrawal method.
    #[init]
    #[payable]
    pub fn new(resolver: AccountId) -> Self {
        let storage_reserve = env::attached_deposit();
        require!(
            storage_reserve >= MIN_STORAGE_RESERVE,
            "Attach at least 1 NEAR as the contract storage reserve"
        );
        Self {
            resolver,
            storage_reserve,
            storage_deposits: NearToken::from_yoctonear(0),
            escrowed_rewards: NearToken::from_yoctonear(0),
            jobs: LookupMap::new(b"j"),
            next_job_id: 0,
        }
    }

    /// Create a fully funded job bound to an order commitment. The attached deposit is the
    /// reward plus the fixed, non-refundable `JOB_STORAGE_DEPOSIT`; the reward must be positive.
    #[payable]
    pub fn create_job(
        &mut self,
        order_sha256: String,
        decision_deadline_ms: u64,
        delivery_deadline_ms: u64,
        acceptance_deadline_ms: u64,
        dispute_deadline_ms: u64,
    ) -> u64 {
        require!(valid_sha256(&order_sha256), "Order hash must be 64 lowercase hex characters");
        let now = env::block_timestamp_ms();
        let deposit = env::attached_deposit();
        require!(
            deposit > JOB_STORAGE_DEPOSIT,
            "Attach the reward plus the job storage deposit (reward must be positive)"
        );
        let reward = deposit.saturating_sub(JOB_STORAGE_DEPOSIT);
        let customer = env::predecessor_account_id();
        require!(customer != self.resolver, "Customer must be distinct from resolver");
        require!(now <= decision_deadline_ms, "Job must be created by the decision deadline");
        require!(
            decision_deadline_ms < delivery_deadline_ms
                && delivery_deadline_ms < acceptance_deadline_ms
                && acceptance_deadline_ms < dispute_deadline_ms,
            "Deadlines must satisfy decision < delivery < acceptance < dispute"
        );
        let id = self.next_job_id;
        self.next_job_id = self.next_job_id.checked_add(1).expect("job id overflow");
        self.storage_deposits = add(self.storage_deposits, JOB_STORAGE_DEPOSIT);
        self.escrowed_rewards = add(self.escrowed_rewards, reward);
        self.jobs.insert(
            id,
            Job {
                customer: customer.clone(),
                worker: None,
                reward,
                order_sha256: order_sha256.clone(),
                decision_deadline_ms,
                delivery_deadline_ms,
                acceptance_deadline_ms,
                dispute_deadline_ms,
                artifact_sha256: None,
                status: JobStatus::Open,
                attempt_counter: 0,
                pending_attempt_id: None,
                publication_consent: false,
            },
        );
        self.assert_solvent();
        emit(
            "job_created",
            json!({
                "job_id": id.to_string(),
                "customer": customer,
                "reward": reward.as_yoctonear().to_string(),
                "storage_deposit": JOB_STORAGE_DEPOSIT.as_yoctonear().to_string(),
                "order_sha256": order_sha256,
                "decision_deadline_ms": decision_deadline_ms.to_string(),
                "delivery_deadline_ms": delivery_deadline_ms.to_string(),
                "acceptance_deadline_ms": acceptance_deadline_ms.to_string(),
                "dispute_deadline_ms": dispute_deadline_ms.to_string(),
            }),
        );
        id
    }

    /// The customer assigns one distinct worker before the delivery deadline.
    pub fn assign(&mut self, job_id: u64, worker: AccountId) {
        let now = env::block_timestamp_ms();
        let caller = env::predecessor_account_id();
        let resolver = self.resolver.clone();
        let job = self.job_mut(job_id);
        require!(caller == job.customer, "Only the customer can assign");
        require!(now < job.delivery_deadline_ms, "Delivery deadline has passed");
        require!(job.status == JobStatus::Open, "Job is not open");
        require!(worker != job.customer && worker != resolver, "Worker must be distinct from customer and resolver");
        job.worker = Some(worker.clone());
        job.status = JobStatus::Assigned;
        self.assert_solvent();
        emit("job_assigned", json!({ "job_id": job_id.to_string(), "customer": caller, "worker": worker }));
    }

    /// Submit one artifact commitment in the decision-to-delivery interval.
    pub fn submit(&mut self, job_id: u64, artifact_sha256: String) {
        require!(valid_sha256(&artifact_sha256), "Artifact hash must be 64 lowercase hex characters");
        let now = env::block_timestamp_ms();
        let caller = env::predecessor_account_id();
        let job = self.job_mut(job_id);
        require!(job.worker.as_ref() == Some(&caller), "Only the assigned worker can submit");
        require!(job.status == JobStatus::Assigned, "Job is not assigned");
        require!(now >= job.decision_deadline_ms, "Submission is before the decision deadline");
        require!(now < job.delivery_deadline_ms, "Delivery deadline has passed");
        job.artifact_sha256 = Some(artifact_sha256.clone());
        job.status = JobStatus::Submitted;
        let order_sha256 = job.order_sha256.clone();
        self.assert_solvent();
        emit(
            "artifact_submitted",
            json!({
                "job_id": job_id.to_string(),
                "worker": caller,
                "artifact_sha256": artifact_sha256,
                "order_sha256": order_sha256,
            }),
        );
    }

    /// Customer accepts exactly the submitted artifact before the acceptance deadline.
    pub fn accept(&mut self, job_id: u64, artifact_sha256: String) -> Promise {
        let now = env::block_timestamp_ms();
        let caller = env::predecessor_account_id();
        let job = self.job_mut(job_id);
        require!(caller == job.customer, "Only the customer can accept");
        require!(job.status == JobStatus::Submitted, "Job is not submitted");
        require!(now < job.acceptance_deadline_ms, "Acceptance deadline has passed");
        require!(job.artifact_sha256.as_deref() == Some(artifact_sha256.as_str()), "Artifact hash does not match submission");
        let worker = job.worker.clone();
        let reward = job.reward;
        emit(
            "job_accepted",
            json!({
                "job_id": job_id.to_string(),
                "customer": caller,
                "worker": worker,
                "artifact_sha256": artifact_sha256,
                "reward": reward.as_yoctonear().to_string(),
            }),
        );
        self.start_transfer(job_id, true)
    }

    /// Either party may dispute a submission before the acceptance boundary.
    pub fn dispute(&mut self, job_id: u64) {
        let now = env::block_timestamp_ms();
        let caller = env::predecessor_account_id();
        let job = self.job_mut(job_id);
        require!(job.status == JobStatus::Submitted, "Job is not submitted");
        require!(caller == job.customer || job.worker.as_ref() == Some(&caller), "Only customer or worker can dispute");
        require!(now < job.acceptance_deadline_ms, "Acceptance deadline has passed");
        job.status = JobStatus::Disputed;
        let artifact = job.artifact_sha256.clone();
        emit("job_disputed", json!({ "job_id": job_id.to_string(), "by": caller, "artifact_sha256": artifact }));
    }

    /// The named resolver makes one explicit pay/refund decision before the dispute deadline.
    pub fn resolve(&mut self, job_id: u64, pay_worker: bool) -> Promise {
        let now = env::block_timestamp_ms();
        let caller = env::predecessor_account_id();
        let resolver = self.resolver.clone();
        let job = self.job_mut(job_id);
        require!(caller == resolver, "Only the resolver can resolve");
        require!(job.status == JobStatus::Disputed, "Job is not disputed");
        require!(now < job.dispute_deadline_ms, "Dispute deadline has passed");
        emit(
            "dispute_resolved",
            json!({ "job_id": job_id.to_string(), "resolver": caller, "pay_worker": pay_worker }),
        );
        self.start_transfer(job_id, pay_worker)
    }

    /// Anyone can trigger a refund after the applicable deadline. Boundaries are inclusive.
    pub fn timeout(&mut self, job_id: u64) -> Promise {
        let now = env::block_timestamp_ms();
        let job = self.job_mut(job_id);
        let eligible = match job.status {
            JobStatus::Open | JobStatus::Assigned => now >= job.delivery_deadline_ms,
            JobStatus::Submitted => now >= job.acceptance_deadline_ms,
            JobStatus::Disputed => now >= job.dispute_deadline_ms,
            _ => false,
        };
        require!(eligible, "Job is not refundable by timeout yet");
        let previous = job.status.as_str();
        emit(
            "job_timeout",
            json!({ "job_id": job_id.to_string(), "by": env::predecessor_account_id(), "previous_status": previous }),
        );
        self.start_transfer(job_id, false)
    }

    /// The customer may cancel an unassigned job before delivery starts; refund is asynchronous.
    pub fn cancel(&mut self, job_id: u64) -> Promise {
        let now = env::block_timestamp_ms();
        let caller = env::predecessor_account_id();
        let job = self.job_mut(job_id);
        require!(caller == job.customer, "Only the customer can cancel");
        require!(job.status == JobStatus::Open, "Only an open job can be cancelled");
        require!(now < job.delivery_deadline_ms, "Delivery deadline has passed");
        emit("job_cancelled", json!({ "job_id": job_id.to_string(), "customer": caller }));
        self.start_transfer(job_id, false)
    }

    /// Retry an already-decided transfer. The decision and beneficiary cannot change.
    pub fn retry_transfer(&mut self, job_id: u64) -> Promise {
        let job = self.job_mut(job_id);
        let pay_worker = match job.status {
            JobStatus::PayoutReady => true,
            JobStatus::RefundReady => false,
            _ => env::panic_str("No failed transfer is ready to retry"),
        };
        emit(
            "transfer_retried",
            json!({ "job_id": job_id.to_string(), "by": env::predecessor_account_id(), "kind": if pay_worker { "payout" } else { "refund" } }),
        );
        self.start_transfer(job_id, pay_worker)
    }

    /// The customer records on chain that the exact accepted artifact may be published.
    /// Consent never transfers to another digest.
    pub fn consent_publication(&mut self, job_id: u64, artifact_sha256: String) {
        let caller = env::predecessor_account_id();
        let job = self.job_mut(job_id);
        require!(caller == job.customer, "Only the customer can consent to publication");
        require!(job.status == JobStatus::Accepted, "Only an accepted job can be published");
        require!(
            job.artifact_sha256.as_deref() == Some(artifact_sha256.as_str()),
            "Artifact hash does not match the accepted artifact"
        );
        require!(!job.publication_consent, "Publication consent already granted");
        job.publication_consent = true;
        self.assert_solvent();
        emit(
            "publication_consent_granted",
            json!({ "job_id": job_id.to_string(), "customer": caller, "artifact_sha256": artifact_sha256 }),
        );
    }

    /// The customer withdraws publication consent. Copies already published elsewhere
    /// cannot be recalled by the contract.
    pub fn revoke_publication(&mut self, job_id: u64) {
        let caller = env::predecessor_account_id();
        let job = self.job_mut(job_id);
        require!(caller == job.customer, "Only the customer can revoke publication consent");
        require!(job.publication_consent, "Publication consent is not granted");
        job.publication_consent = false;
        let artifact = job.artifact_sha256.clone();
        emit(
            "publication_consent_revoked",
            json!({ "job_id": job_id.to_string(), "customer": caller, "artifact_sha256": artifact }),
        );
    }

    /// Private callback for exactly one in-flight transfer attempt.
    #[private]
    pub fn on_transfer_complete(&mut self, job_id: u64, attempt_id: u64) -> bool {
        let succeeded = matches!(env::promise_result(0), PromiseResult::Successful(_));
        let (reward, was_payout, recipient, status) = {
            let job = self.job_mut(job_id);
            require!(
                matches!(job.status, JobStatus::PayoutPending | JobStatus::RefundPending),
                "Job has no pending transfer"
            );
            require!(job.pending_attempt_id == Some(attempt_id), "Transfer attempt does not match");
            let was_payout = job.status == JobStatus::PayoutPending;
            job.pending_attempt_id = None;
            if succeeded {
                job.status = if was_payout { JobStatus::Accepted } else { JobStatus::Refunded };
            } else {
                // Preserve the already-final entitlement. A failed accepted payout never becomes a
                // customer refund; a failed refund never becomes a worker payout.
                job.status = if was_payout { JobStatus::PayoutReady } else { JobStatus::RefundReady };
            }
            let recipient = if was_payout { job.worker.clone() } else { Some(job.customer.clone()) };
            (job.reward, was_payout, recipient, job.status.as_str())
        };
        if succeeded {
            self.escrowed_rewards = NearToken::from_yoctonear(
                self.escrowed_rewards.as_yoctonear().checked_sub(reward.as_yoctonear()).expect("reward liability underflow"),
            );
        }
        emit(
            if succeeded { "transfer_settled" } else { "transfer_failed" },
            json!({
                "job_id": job_id.to_string(),
                "attempt_id": attempt_id.to_string(),
                "kind": if was_payout { "payout" } else { "refund" },
                "recipient": recipient,
                "amount": reward.as_yoctonear().to_string(),
                "status": status,
            }),
        );
        succeeded
    }

    pub fn get_job(&self, id: u64) -> Option<JobView> {
        self.jobs.get(&id).map(|job| JobView {
            id,
            customer: job.customer.clone(),
            worker: job.worker.clone(),
            reward: job.reward,
            order_sha256: job.order_sha256.clone(),
            decision_deadline_ms: job.decision_deadline_ms,
            delivery_deadline_ms: job.delivery_deadline_ms,
            acceptance_deadline_ms: job.acceptance_deadline_ms,
            dispute_deadline_ms: job.dispute_deadline_ms,
            artifact_sha256: job.artifact_sha256.clone(),
            status: job.status.as_str().to_string(),
            pending_attempt_id: job.pending_attempt_id,
            publication_consent: job.publication_consent,
        })
    }

    pub fn job_count(&self) -> u64 {
        self.next_job_id
    }

    pub fn get_resolver(&self) -> AccountId {
        self.resolver.clone()
    }

    pub fn get_storage_reserve(&self) -> NearToken {
        self.storage_reserve
    }

    /// Sum of the non-refundable per-job storage deposits received so far.
    pub fn get_storage_deposits(&self) -> NearToken {
        self.storage_deposits
    }

    /// Sum of rewards whose transfer has not yet been confirmed successful.
    pub fn get_escrowed_rewards(&self) -> NearToken {
        self.escrowed_rewards
    }

    pub fn get_config(&self) -> ConfigView {
        ConfigView {
            resolver: self.resolver.clone(),
            storage_reserve: self.storage_reserve,
            job_storage_deposit: JOB_STORAGE_DEPOSIT,
            storage_deposits: self.storage_deposits,
            escrowed_rewards: self.escrowed_rewards,
            callback_gas: CALLBACK_GAS,
            job_count: self.next_job_id,
            event_standard: EVENT_STANDARD.to_string(),
            event_version: EVENT_VERSION.to_string(),
        }
    }

    fn job_mut(&mut self, id: u64) -> &mut Job {
        self.jobs.get_mut(&id).unwrap_or_else(|| env::panic_str("Job does not exist"))
    }

    /// Balance invariant, checked after every call that adds liabilities or storage:
    /// (1) the balance covers escrowed rewards, the init reserve and all per-job storage
    /// deposits (none of these is ever paid out except the rewards themselves), and
    /// (2) the protocol storage stake never draws on escrowed rewards.
    fn assert_solvent(&self) {
        let balance = env::account_balance().as_yoctonear();
        let escrowed = self.escrowed_rewards.as_yoctonear();
        let required = add(add(self.escrowed_rewards, self.storage_reserve), self.storage_deposits);
        require!(balance >= required.as_yoctonear(), "Contract balance does not cover rewards and reserves");
        let staked = (env::storage_usage() as u128)
            .checked_mul(env::storage_byte_cost().as_yoctonear())
            .expect("storage cost overflow");
        require!(balance - escrowed >= staked, "Storage stake would draw on escrowed rewards");
    }

    fn start_transfer(&mut self, id: u64, pay_worker: bool) -> Promise {
        let job = self.job_mut(id);
        let status_allows = if pay_worker {
            matches!(job.status, JobStatus::Submitted | JobStatus::Disputed | JobStatus::PayoutReady)
        } else {
            matches!(job.status, JobStatus::Open | JobStatus::Assigned | JobStatus::Submitted | JobStatus::Disputed | JobStatus::RefundReady)
        };
        require!(status_allows, "Job is not eligible for transfer");
        let recipient = if pay_worker { job.worker.clone().unwrap_or_else(|| env::panic_str("Job has no assigned worker")) } else { job.customer.clone() };
        job.attempt_counter = job.attempt_counter.checked_add(1).expect("transfer attempt id overflow");
        let attempt_id = job.attempt_counter;
        job.pending_attempt_id = Some(attempt_id);
        job.status = if pay_worker { JobStatus::PayoutPending } else { JobStatus::RefundPending };
        Promise::new(recipient)
            .transfer(job.reward)
            .then(Self::ext(env::current_account_id()).with_static_gas(CALLBACK_GAS).on_transfer_complete(id, attempt_id))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::{get_logs, VMContextBuilder};
    use near_sdk::testing_env;
    #[allow(deprecated)]
    use near_sdk::test_utils::testing_env_with_promise_results;

    const DECISION: u64 = 1_000;
    const DELIVERY: u64 = 2_000;
    const ACCEPTANCE: u64 = 3_000;
    const DISPUTE: u64 = 4_000;
    const HASH: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const OTHER_HASH: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const ORDER: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    fn account(name: &str) -> AccountId { name.parse().unwrap() }
    fn near(value: u128) -> NearToken { NearToken::from_near(value) }
    fn zero() -> NearToken { NearToken::from_yoctonear(0) }
    /// Deposit that yields exactly `reward` in escrow.
    fn funded(reward: NearToken) -> NearToken { add(reward, JOB_STORAGE_DEPOSIT) }

    fn context(predecessor: &str, timestamp: u64, deposit: NearToken) {
        let mut builder = VMContextBuilder::new();
        builder
            .current_account_id(account("escrow.near"))
            .signer_account_id(account(predecessor))
            .predecessor_account_id(account(predecessor))
            .block_timestamp(timestamp * 1_000_000)
            .account_balance(near(100))
            .attached_deposit(deposit);
        testing_env!(builder.build());
    }

    #[allow(deprecated)]
    fn callback_context(timestamp: u64, result: PromiseResult) {
        let mut builder = VMContextBuilder::new();
        builder
            .current_account_id(account("escrow.near"))
            .signer_account_id(account("escrow.near"))
            .predecessor_account_id(account("escrow.near"))
            .block_timestamp(timestamp * 1_000_000)
            .account_balance(near(100));
        testing_env_with_promise_results(builder.build(), result);
    }

    fn panics<F: FnOnce()>(f: F) -> bool {
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(f)).is_err()
    }

    fn events() -> Vec<Value> {
        get_logs()
            .iter()
            .filter_map(|line| line.strip_prefix("EVENT_JSON:"))
            .map(|body| near_sdk::serde_json::from_str::<Value>(body).unwrap())
            .collect()
    }

    fn setup() -> ForecastJobs {
        context("deployer.near", 500, near(1));
        ForecastJobs::new(account("resolver.near"))
    }

    fn open_job(contract: &mut ForecastJobs) -> u64 {
        context("customer.near", 500, funded(near(2)));
        contract.create_job(ORDER.to_string(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE)
    }

    fn submitted_job(contract: &mut ForecastJobs) -> u64 {
        let id = open_job(contract);
        context("customer.near", 600, zero());
        contract.assign(id, account("worker.near"));
        context("worker.near", DECISION, zero());
        contract.submit(id, HASH.to_string());
        id
    }

    fn accepted_job(contract: &mut ForecastJobs) -> u64 {
        let id = submitted_job(contract);
        context("customer.near", 2_500, zero());
        contract.accept(id, HASH.to_string());
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        callback_context(2_500, PromiseResult::Successful(vec![]));
        assert!(contract.on_transfer_complete(id, attempt));
        id
    }

    #[test]
    fn accepted_payout_failure_preserves_worker_entitlement_and_can_retry_once() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("customer.near", 2_500, zero());
        contract.accept(id, HASH.to_string());
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert_eq!(contract.get_job(id).unwrap().status, "PAYOUT_PENDING");
        assert_eq!(contract.get_escrowed_rewards(), near(2));

        callback_context(2_500, PromiseResult::Failed);
        assert!(!contract.on_transfer_complete(id, attempt));
        assert_eq!(contract.get_job(id).unwrap().status, "PAYOUT_READY");
        assert!(contract.get_job(id).unwrap().pending_attempt_id.is_none());
        assert!(panics(|| {
            context("anyone.near", ACCEPTANCE, zero());
            contract.timeout(id);
        }));

        context("anyone.near", 3_500, zero());
        contract.retry_transfer(id);
        let retry = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert!(retry > attempt);
        callback_context(3_500, PromiseResult::Successful(vec![]));
        assert!(contract.on_transfer_complete(id, retry));
        assert_eq!(contract.get_job(id).unwrap().status, "ACCEPTED");
        assert_eq!(contract.get_escrowed_rewards(), zero());
        assert!(panics(|| { contract.on_transfer_complete(id, retry); }));
    }

    #[test]
    fn refund_failure_preserves_customer_entitlement_and_cannot_become_payout() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("customer.near", ACCEPTANCE, zero());
        contract.timeout(id);
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        callback_context(ACCEPTANCE, PromiseResult::Failed);
        assert!(!contract.on_transfer_complete(id, attempt));
        assert_eq!(contract.get_job(id).unwrap().status, "REFUND_READY");
        assert_eq!(contract.get_escrowed_rewards(), near(2));
        assert!(panics(|| {
            context("customer.near", 2_900, zero());
            contract.accept(id, HASH.to_string());
        }));
        context("anyone.near", 3_500, zero());
        contract.retry_transfer(id);
        let retry = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        callback_context(3_500, PromiseResult::Successful(vec![]));
        assert!(contract.on_transfer_complete(id, retry));
        assert_eq!(contract.get_job(id).unwrap().status, "REFUNDED");
        assert_eq!(contract.get_escrowed_rewards(), zero());
    }

    #[test]
    fn actors_hash_and_deadline_boundaries_are_enforced() {
        let mut contract = setup();
        let id = open_job(&mut contract);
        context("worker.near", 500, zero());
        assert!(panics(|| contract.assign(id, account("worker.near"))));
        context("customer.near", 600, zero());
        contract.assign(id, account("worker.near"));
        context("worker.near", DECISION - 1, zero());
        assert!(panics(|| contract.submit(id, HASH.into())));
        context("worker.near", DECISION, zero());
        assert!(panics(|| contract.submit(id, "ABC".into())));
        contract.submit(id, HASH.into());
        context("customer.near", ACCEPTANCE, zero());
        assert!(panics(|| { contract.accept(id, HASH.into()); }));
    }

    #[test]
    fn creation_requires_reward_above_storage_deposit_and_ordered_deadlines_without_a_job_cap() {
        context("deployer.near", 500, NearToken::from_millinear(500));
        assert!(std::panic::catch_unwind(|| ForecastJobs::new(account("resolver.near"))).is_err());

        let mut contract = setup();
        for deposit in [zero(), NearToken::from_millinear(5), JOB_STORAGE_DEPOSIT] {
            context("customer.near", 500, deposit);
            assert!(panics(|| { contract.create_job(ORDER.into(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE); }));
        }
        context("customer.near", 500, near(1));
        assert!(panics(|| { contract.create_job(ORDER.into(), DECISION, DECISION, ACCEPTANCE, DISPUTE); }));
        context("resolver.near", 500, near(1));
        assert!(panics(|| { contract.create_job(ORDER.into(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE); }));
        assert_eq!(contract.job_count(), 0);

        // The old lifetime cap of ten jobs is gone: each job pays for its own record.
        // A 1-yoctoNEAR reward still costs the caller the full storage deposit.
        let one_yocto = NearToken::from_yoctonear(1);
        for _ in 0..25 {
            context("stranger.near", 500, funded(one_yocto));
            contract.create_job(ORDER.into(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE);
        }
        assert_eq!(contract.job_count(), 25);
        assert_eq!(contract.get_escrowed_rewards(), NearToken::from_yoctonear(25));
        assert_eq!(contract.get_storage_deposits().as_yoctonear(), 25 * JOB_STORAGE_DEPOSIT.as_yoctonear());
    }

    #[test]
    fn order_hash_is_validated_stored_and_returned() {
        let mut contract = setup();
        for bad in ["", "ABC", &ORDER.to_uppercase(), &ORDER[..63], &format!("{ORDER}0"), &ORDER.replace('0', "g")] {
            context("customer.near", 500, funded(near(1)));
            assert!(panics(|| { contract.create_job(bad.to_string(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE); }), "accepted bad order hash {bad:?}");
        }
        let id = open_job(&mut contract);
        let view = contract.get_job(id).unwrap();
        assert_eq!(view.order_sha256, ORDER);
        assert_eq!(view.reward, near(2));
        assert_eq!(
            [view.decision_deadline_ms, view.delivery_deadline_ms, view.acceptance_deadline_ms, view.dispute_deadline_ms],
            [DECISION, DELIVERY, ACCEPTANCE, DISPUTE]
        );
        assert!(!view.publication_consent);
    }

    #[test]
    fn storage_deposit_is_kept_while_reward_liability_returns_to_zero() {
        let mut contract = setup();
        let paid = accepted_job(&mut contract);
        let refunded = open_job(&mut contract);
        context("customer.near", 700, zero());
        contract.cancel(refunded);
        let attempt = contract.get_job(refunded).unwrap().pending_attempt_id.unwrap();
        callback_context(700, PromiseResult::Successful(vec![]));
        assert!(contract.on_transfer_complete(refunded, attempt));
        assert_eq!(contract.get_job(paid).unwrap().status, "ACCEPTED");
        assert_eq!(contract.get_job(refunded).unwrap().status, "REFUNDED");
        assert_eq!(contract.get_escrowed_rewards(), zero());
        assert_eq!(contract.get_storage_deposits().as_yoctonear(), 2 * JOB_STORAGE_DEPOSIT.as_yoctonear());
        let config = contract.get_config();
        assert_eq!(config.job_storage_deposit, JOB_STORAGE_DEPOSIT);
        assert_eq!(config.storage_reserve, near(1));
        assert_eq!(config.callback_gas, CALLBACK_GAS);
        assert_eq!(config.job_count, 2);
    }

    #[test]
    fn balance_must_cover_rewards_reserve_and_storage_deposits() {
        // A unit test does not roll back state after a panic, so each case uses a fresh contract.
        // The runtime reports the pre-call balance plus the attached deposit. The mocked
        // account stakes 300 KiB of default storage (3.072 NEAR).
        let with_balance = |balance: NearToken, deposit: NearToken| {
            let mut builder = VMContextBuilder::new();
            builder
                .current_account_id(account("escrow.near"))
                .predecessor_account_id(account("customer.near"))
                .block_timestamp(500 * 1_000_000)
                .account_balance(balance)
                .attached_deposit(deposit);
            testing_env!(builder.build());
        };
        // 0.5 NEAR before the call does not cover the 1 NEAR init reserve.
        let mut contract = setup();
        with_balance(NearToken::from_millinear(500), funded(near(2)));
        assert!(panics(|| { contract.create_job(ORDER.into(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE); }));
        // 2 NEAR covers the reserve but the 3.072 NEAR storage stake would draw on escrow.
        let mut contract = setup();
        with_balance(near(2), funded(near(2)));
        assert!(panics(|| { contract.create_job(ORDER.into(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE); }));
        let mut contract = setup();
        with_balance(near(4), funded(near(2)));
        contract.create_job(ORDER.into(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE);
        assert_eq!(contract.get_escrowed_rewards(), near(2));
    }

    #[test]
    fn worst_case_job_record_fits_the_storage_deposit_with_2x_margin() {
        let customer = format!("{}.testnet", "c".repeat(56));
        let worker = format!("{}.testnet", "w".repeat(56));
        assert_eq!((customer.len(), worker.len()), (64, 64));
        let mut contract = setup();
        contract.jobs.flush();
        let mut bytes = 0u64;
        let mut measure = |contract: &mut ForecastJobs, before: u64| {
            contract.jobs.flush();
            bytes += env::storage_usage() - before;
        };

        context(&customer, 500, funded(near(1)));
        let before = env::storage_usage();
        let id = contract.create_job(ORDER.into(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE);
        measure(&mut contract, before);
        context(&customer, 600, zero());
        let before = env::storage_usage();
        contract.assign(id, account(&worker));
        measure(&mut contract, before);
        context(&worker, DECISION, zero());
        let before = env::storage_usage();
        contract.submit(id, HASH.into());
        measure(&mut contract, before);
        // The record is largest while a transfer is pending (Some(attempt_id)).
        context(&customer, 2_500, zero());
        let before = env::storage_usage();
        contract.accept(id, HASH.into());
        measure(&mut contract, before);
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        callback_context(2_500, PromiseResult::Successful(vec![]));
        let before = env::storage_usage();
        contract.on_transfer_complete(id, attempt);
        contract.jobs.flush();
        let settled_shrink = before - env::storage_usage();
        context(&customer, 2_600, zero());
        let before = env::storage_usage();
        contract.consent_publication(id, HASH.into());
        contract.jobs.flush();
        assert_eq!(env::storage_usage(), before, "consent flips a bool and must not grow the record");
        assert_eq!(settled_shrink, 8, "settlement clears Some(attempt_id)");

        // Key "j" + u64 (9 bytes) + Borsh record + 40 bytes protocol per-record overhead.
        let cost = bytes as u128 * env::storage_byte_cost().as_yoctonear();
        println!("worst-case job record: {bytes} bytes = {cost} yoctoNEAR; deposit {} yoctoNEAR", JOB_STORAGE_DEPOSIT.as_yoctonear());
        assert_eq!(bytes, 390, "worst-case record size changed; re-derive JOB_STORAGE_DEPOSIT");
        assert!(JOB_STORAGE_DEPOSIT.as_yoctonear() >= 2 * cost, "storage deposit has less than 2x margin");
    }

    #[test]
    fn consent_only_for_the_accepted_hash_by_the_customer_and_can_be_revoked() {
        let mut contract = setup();
        let submitted = submitted_job(&mut contract);
        context("customer.near", 2_500, zero());
        assert!(panics(|| contract.consent_publication(submitted, HASH.into())), "consent before ACCEPTED");

        let id = accepted_job(&mut contract);
        context("worker.near", 2_600, zero());
        assert!(panics(|| contract.consent_publication(id, HASH.into())), "worker consent");
        context("customer.near", 2_600, zero());
        assert!(panics(|| contract.consent_publication(id, OTHER_HASH.into())), "consent for another hash");
        assert!(panics(|| contract.revoke_publication(id)), "revoke before grant");
        assert!(!contract.get_job(id).unwrap().publication_consent);
        contract.consent_publication(id, HASH.into());
        assert!(contract.get_job(id).unwrap().publication_consent);
        assert!(panics(|| contract.consent_publication(id, HASH.into())), "double grant");
        context("stranger.near", 2_700, zero());
        assert!(panics(|| contract.revoke_publication(id)), "stranger revoke");
        context("customer.near", 2_700, zero());
        contract.revoke_publication(id);
        assert!(!contract.get_job(id).unwrap().publication_consent);

        // A refunded job can never be consented.
        let refunded = submitted_job(&mut contract);
        context("anyone.near", ACCEPTANCE, zero());
        contract.timeout(refunded);
        let attempt = contract.get_job(refunded).unwrap().pending_attempt_id.unwrap();
        callback_context(ACCEPTANCE, PromiseResult::Successful(vec![]));
        contract.on_transfer_complete(refunded, attempt);
        context("customer.near", ACCEPTANCE, zero());
        assert!(panics(|| contract.consent_publication(refunded, HASH.into())), "consent on refunded job");
    }

    #[test]
    fn nep297_events_are_emitted_for_each_transition() {
        let mut contract = setup();
        context("customer.near", 500, funded(near(2)));
        let id = contract.create_job(ORDER.into(), DECISION, DELIVERY, ACCEPTANCE, DISPUTE);
        let created = events();
        assert_eq!(created.len(), 1);
        let event = &created[0];
        assert_eq!(event["standard"], "forecast_jobs");
        assert_eq!(event["version"], "1.0.0");
        assert_eq!(event["event"], "job_created");
        let data = &event["data"][0];
        assert_eq!(data["job_id"], "0");
        assert_eq!(data["customer"], "customer.near");
        assert_eq!(data["order_sha256"], ORDER);
        assert_eq!(data["reward"], near(2).as_yoctonear().to_string());
        assert_eq!(data["storage_deposit"], JOB_STORAGE_DEPOSIT.as_yoctonear().to_string());
        assert_eq!(data["dispute_deadline_ms"], DISPUTE.to_string());

        let mut seen = vec![];
        let mut step = |seen: &mut Vec<String>| {
            for event in events() {
                seen.push(event["event"].as_str().unwrap().to_string());
            }
        };
        context("customer.near", 600, zero());
        contract.assign(id, account("worker.near"));
        assert_eq!(events()[0]["data"][0]["worker"], "worker.near");
        step(&mut seen);
        context("worker.near", DECISION, zero());
        contract.submit(id, HASH.into());
        assert_eq!(events()[0]["data"][0]["artifact_sha256"], HASH);
        step(&mut seen);
        context("customer.near", 2_500, zero());
        contract.dispute(id);
        step(&mut seen);
        context("resolver.near", 3_500, zero());
        contract.resolve(id, true);
        step(&mut seen);
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        callback_context(3_500, PromiseResult::Failed);
        contract.on_transfer_complete(id, attempt);
        assert_eq!(events()[0]["data"][0]["status"], "PAYOUT_READY");
        step(&mut seen);
        context("anyone.near", 3_600, zero());
        contract.retry_transfer(id);
        step(&mut seen);
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        callback_context(3_600, PromiseResult::Successful(vec![]));
        contract.on_transfer_complete(id, attempt);
        let settled = &events()[0]["data"][0];
        assert_eq!(settled["recipient"], "worker.near");
        assert_eq!(settled["amount"], near(2).as_yoctonear().to_string());
        assert_eq!(settled["kind"], "payout");
        step(&mut seen);
        context("customer.near", 3_700, zero());
        contract.consent_publication(id, HASH.into());
        step(&mut seen);
        context("customer.near", 3_800, zero());
        contract.revoke_publication(id);
        step(&mut seen);

        let cancelled = open_job(&mut contract);
        context("customer.near", 700, zero());
        contract.cancel(cancelled);
        step(&mut seen);
        let timed_out = open_job(&mut contract);
        context("anyone.near", DELIVERY, zero());
        contract.timeout(timed_out);
        assert_eq!(events()[0]["data"][0]["previous_status"], "OPEN");
        step(&mut seen);
        let accepted = submitted_job(&mut contract);
        context("customer.near", 2_500, zero());
        contract.accept(accepted, HASH.into());
        step(&mut seen);

        assert_eq!(
            seen,
            [
                "job_assigned", "artifact_submitted", "job_disputed", "dispute_resolved", "transfer_failed",
                "transfer_retried", "transfer_settled", "publication_consent_granted", "publication_consent_revoked",
                "job_cancelled", "job_timeout", "job_accepted",
            ]
        );
    }

    #[test]
    fn submitted_hash_must_match_and_pending_payout_cannot_be_repeated_or_refunded() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("customer.near", 2_500, zero());
        assert!(panics(|| { contract.accept(id, OTHER_HASH.into()); }));
        contract.accept(id, HASH.into());
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert!(panics(|| { contract.accept(id, HASH.into()); }));
        context("anyone.near", ACCEPTANCE, zero());
        assert!(panics(|| { contract.timeout(id); }));
        callback_context(2_600, PromiseResult::Failed);
        assert!(panics(|| { contract.on_transfer_complete(id, attempt + 1); }));
        assert_eq!(contract.get_job(id).unwrap().pending_attempt_id, Some(attempt));
    }

    #[test]
    fn dispute_can_only_be_resolved_once_and_boundary_timeout_wins() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("customer.near", 2_500, zero());
        contract.dispute(id);
        context("resolver.near", DISPUTE, zero());
        contract.timeout(id);
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert!(panics(|| { contract.resolve(id, true); }));
        callback_context(DISPUTE, PromiseResult::Failed);
        assert!(!contract.on_transfer_complete(id, attempt));
        assert_eq!(contract.get_job(id).unwrap().status, "REFUND_READY");
    }

    #[test]
    fn open_cancel_and_assigned_timeout_refund_at_boundaries() {
        let mut contract = setup();
        let open_id = open_job(&mut contract);
        context("customer.near", DELIVERY - 1, zero());
        contract.cancel(open_id);
        assert_eq!(contract.get_job(open_id).unwrap().status, "REFUND_PENDING");

        let assigned_id = open_job(&mut contract);
        context("customer.near", 600, zero());
        contract.assign(assigned_id, account("worker.near"));
        context("anyone.near", DELIVERY, zero());
        contract.timeout(assigned_id);
        assert_eq!(contract.get_job(assigned_id).unwrap().status, "REFUND_PENDING");
    }

    #[test]
    fn dispute_resolver_and_timeout_race_have_one_outcome() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("worker.near", 2_500, zero());
        contract.dispute(id);
        context("customer.near", 3_500, zero());
        assert!(panics(|| { contract.resolve(id, true); }));
        context("resolver.near", 3_500, zero());
        contract.resolve(id, false);
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert!(panics(|| { contract.timeout(id); }));
        callback_context(3_500, PromiseResult::Successful(vec![]));
        assert!(contract.on_transfer_complete(id, attempt));
        assert_eq!(contract.get_job(id).unwrap().status, "REFUNDED");
    }
}
