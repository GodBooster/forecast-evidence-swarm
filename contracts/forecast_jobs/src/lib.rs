//! Minimal escrow for synthetic forecast delivery jobs.
//!
//! The contract records acceptance and transfers only the fixed reward. It does not inspect
//! evidence, judge forecasts, or authenticate artifact contents. A digest binds bytes only.

use near_sdk::store::LookupMap;
use near_sdk::{env, near, require, AccountId, Gas, NearToken, PanicOnDefault, Promise, PromiseResult};

const MAX_JOBS: u64 = 10;
const STORAGE_RESERVE_PER_JOB: NearToken = NearToken::from_millinear(100);
const MIN_STORAGE_RESERVE: NearToken = NearToken::from_near(1);
const CALLBACK_GAS: Gas = Gas::from_tgas(10);

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct ForecastJobs {
    resolver: AccountId,
    // Contract-level, non-withdrawable operating/storage reserve funded at initialization.
    // Job rewards are held and accounted for separately in each Job.
    storage_reserve: NearToken,
    storage_reserved_for_jobs: NearToken,
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
    decision_deadline_ms: u64,
    delivery_deadline_ms: u64,
    acceptance_deadline_ms: u64,
    dispute_deadline_ms: u64,
    artifact_sha256: Option<String>,
    status: JobStatus,
    attempt_counter: u64,
    pending_attempt_id: Option<u64>,
}

#[near(serializers = [json])]
pub struct JobView {
    pub id: u64,
    pub customer: AccountId,
    pub worker: Option<AccountId>,
    pub reward: NearToken,
    pub decision_deadline_ms: u64,
    pub delivery_deadline_ms: u64,
    pub acceptance_deadline_ms: u64,
    pub dispute_deadline_ms: u64,
    pub artifact_sha256: Option<String>,
    pub status: String,
    pub pending_attempt_id: Option<u64>,
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
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
            storage_reserved_for_jobs: NearToken::from_yoctonear(0),
            escrowed_rewards: NearToken::from_yoctonear(0),
            jobs: LookupMap::new(b"j"),
            next_job_id: 0,
        }
    }

    /// Create a fully funded job. The attached deposit is exactly the reward escrow.
    #[payable]
    pub fn create_job(
        &mut self,
        decision_deadline_ms: u64,
        delivery_deadline_ms: u64,
        acceptance_deadline_ms: u64,
        dispute_deadline_ms: u64,
    ) -> u64 {
        let now = env::block_timestamp_ms();
        let reward = env::attached_deposit();
        require!(!reward.is_zero(), "Attach a positive reward");
        require!(env::predecessor_account_id() != self.resolver, "Customer must be distinct from resolver");
        require!(now <= decision_deadline_ms, "Job must be created by the decision deadline");
        require!(
            decision_deadline_ms < delivery_deadline_ms
                && delivery_deadline_ms < acceptance_deadline_ms
                && acceptance_deadline_ms < dispute_deadline_ms,
            "Deadlines must satisfy decision < delivery < acceptance < dispute"
        );
        let next_storage_reserved = self
            .storage_reserved_for_jobs
            .checked_add(STORAGE_RESERVE_PER_JOB)
            .expect("storage reserve accounting overflow");
        require!(
            self.next_job_id < MAX_JOBS && next_storage_reserved <= self.storage_reserve,
            "Job capacity or storage reserve exhausted"
        );
        let next_escrowed = NearToken::from_yoctonear(
            self.escrowed_rewards.as_yoctonear().checked_add(reward.as_yoctonear()).expect("reward accounting overflow"),
        );
        // Keep aggregate job liabilities and the original storage reserve fully collateralized.
        let minimum_balance = next_escrowed.as_yoctonear()
            .checked_add(self.storage_reserve.as_yoctonear())
            .expect("balance accounting overflow");
        require!(env::account_balance().as_yoctonear() >= minimum_balance, "Contract balance does not cover reward and storage reserve");
        let id = self.next_job_id;
        self.next_job_id = self.next_job_id.checked_add(1).expect("job id overflow");
        self.storage_reserved_for_jobs = next_storage_reserved;
        self.escrowed_rewards = next_escrowed;
        self.jobs.insert(
            id,
            Job {
                customer: env::predecessor_account_id(),
                worker: None,
                reward,
                decision_deadline_ms,
                delivery_deadline_ms,
                acceptance_deadline_ms,
                dispute_deadline_ms,
                artifact_sha256: None,
                status: JobStatus::Open,
                attempt_counter: 0,
                pending_attempt_id: None,
            },
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
        job.worker = Some(worker);
        job.status = JobStatus::Assigned;
    }

    /// Submit one artifact commitment in the decision-to-delivery interval.
    pub fn submit(&mut self, job_id: u64, artifact_sha256: String) {
        require!(valid_sha256(&artifact_sha256), "Artifact hash must be 64 lowercase hex characters");
        let now = env::block_timestamp_ms();
        let job = self.job_mut(job_id);
        require!(job.worker.as_ref() == Some(&env::predecessor_account_id()), "Only the assigned worker can submit");
        require!(job.status == JobStatus::Assigned, "Job is not assigned");
        require!(now >= job.decision_deadline_ms, "Submission is before the decision deadline");
        require!(now < job.delivery_deadline_ms, "Delivery deadline has passed");
        job.artifact_sha256 = Some(artifact_sha256);
        job.status = JobStatus::Submitted;
    }

    /// Customer accepts exactly the submitted artifact before the acceptance deadline.
    pub fn accept(&mut self, job_id: u64, artifact_sha256: String) -> Promise {
        let now = env::block_timestamp_ms();
        let job = self.job_mut(job_id);
        require!(env::predecessor_account_id() == job.customer, "Only the customer can accept");
        require!(job.status == JobStatus::Submitted, "Job is not submitted");
        require!(now < job.acceptance_deadline_ms, "Acceptance deadline has passed");
        require!(job.artifact_sha256.as_deref() == Some(artifact_sha256.as_str()), "Artifact hash does not match submission");
        self.start_transfer(job_id, true)
    }

    /// Either party may dispute a submission before the acceptance boundary.
    pub fn dispute(&mut self, job_id: u64) {
        let now = env::block_timestamp_ms();
        let job = self.job_mut(job_id);
        let caller = env::predecessor_account_id();
        require!(job.status == JobStatus::Submitted, "Job is not submitted");
        require!(caller == job.customer || job.worker.as_ref() == Some(&caller), "Only customer or worker can dispute");
        require!(now < job.acceptance_deadline_ms, "Acceptance deadline has passed");
        job.status = JobStatus::Disputed;
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
        self.start_transfer(job_id, false)
    }

    /// The customer may cancel an unassigned job before delivery starts; refund is asynchronous.
    pub fn cancel(&mut self, job_id: u64) -> Promise {
        let now = env::block_timestamp_ms();
        let job = self.job_mut(job_id);
        require!(env::predecessor_account_id() == job.customer, "Only the customer can cancel");
        require!(job.status == JobStatus::Open, "Only an open job can be cancelled");
        require!(now < job.delivery_deadline_ms, "Delivery deadline has passed");
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
        self.start_transfer(job_id, pay_worker)
    }

    /// Private callback for exactly one in-flight transfer attempt.
    #[private]
    pub fn on_transfer_complete(&mut self, job_id: u64, attempt_id: u64) -> bool {
        let succeeded = matches!(env::promise_result(0), PromiseResult::Successful(_));
        let reward = {
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
            job.reward
        };
        if succeeded {
            self.escrowed_rewards = NearToken::from_yoctonear(
                self.escrowed_rewards.as_yoctonear().checked_sub(reward.as_yoctonear()).expect("reward liability underflow"),
            );
        }
        succeeded
    }

    pub fn get_job(&self, id: u64) -> Option<JobView> {
        self.jobs.get(&id).map(|job| JobView {
            id,
            customer: job.customer.clone(),
            worker: job.worker.clone(),
            reward: job.reward,
            decision_deadline_ms: job.decision_deadline_ms,
            delivery_deadline_ms: job.delivery_deadline_ms,
            acceptance_deadline_ms: job.acceptance_deadline_ms,
            dispute_deadline_ms: job.dispute_deadline_ms,
            artifact_sha256: job.artifact_sha256.clone(),
            status: job.status.as_str().to_string(),
            pending_attempt_id: job.pending_attempt_id,
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

    pub fn get_storage_reserved_for_jobs(&self) -> NearToken {
        self.storage_reserved_for_jobs
    }

    /// Sum of rewards whose transfer has not yet been confirmed successful.
    pub fn get_escrowed_rewards(&self) -> NearToken {
        self.escrowed_rewards
    }

    fn job_mut(&mut self, id: u64) -> &mut Job {
        self.jobs.get_mut(&id).unwrap_or_else(|| env::panic_str("Job does not exist"))
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
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::testing_env;
    #[allow(deprecated)]
    use near_sdk::test_utils::testing_env_with_promise_results;

    const DECISION: u64 = 1_000;
    const DELIVERY: u64 = 2_000;
    const ACCEPTANCE: u64 = 3_000;
    const DISPUTE: u64 = 4_000;
    const HASH: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const OTHER_HASH: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

    fn account(name: &str) -> AccountId { name.parse().unwrap() }
    fn near(value: u128) -> NearToken { NearToken::from_near(value) }

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
    fn callback_context(predecessor: &str, timestamp: u64, result: PromiseResult) {
        let mut builder = VMContextBuilder::new();
        builder
            .current_account_id(account("escrow.near"))
            .signer_account_id(account("escrow.near"))
            .predecessor_account_id(account("escrow.near"))
            .block_timestamp(timestamp * 1_000_000)
            .account_balance(near(100));
        testing_env_with_promise_results(builder.build(), result);
        let _ = predecessor;
    }

    fn setup() -> ForecastJobs {
        context("deployer.near", 500, near(1));
        ForecastJobs::new(account("resolver.near"))
    }

    fn open_job(contract: &mut ForecastJobs) -> u64 {
        context("customer.near", 500, near(2));
        contract.create_job(DECISION, DELIVERY, ACCEPTANCE, DISPUTE)
    }

    fn submitted_job(contract: &mut ForecastJobs) -> u64 {
        let id = open_job(contract);
        context("customer.near", 600, NearToken::from_yoctonear(0));
        contract.assign(id, account("worker.near"));
        context("worker.near", DECISION, NearToken::from_yoctonear(0));
        contract.submit(id, HASH.to_string());
        id
    }

    #[test]
    fn accepted_payout_failure_preserves_worker_entitlement_and_can_retry_once() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("customer.near", 2_500, NearToken::from_yoctonear(0));
        contract.accept(id, HASH.to_string());
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert_eq!(contract.get_job(id).unwrap().status, "PAYOUT_PENDING");
        assert_eq!(contract.get_escrowed_rewards(), near(2));

        callback_context("escrow.near", 2_500, PromiseResult::Failed);
        assert!(!contract.on_transfer_complete(id, attempt));
        assert_eq!(contract.get_job(id).unwrap().status, "PAYOUT_READY");
        assert!(contract.get_job(id).unwrap().pending_attempt_id.is_none());
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            context("anyone.near", ACCEPTANCE, NearToken::from_yoctonear(0));
            contract.timeout(id);
        })).is_err());

        context("anyone.near", 3_500, NearToken::from_yoctonear(0));
        contract.retry_transfer(id);
        let retry = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert!(retry > attempt);
        callback_context("escrow.near", 3_500, PromiseResult::Successful(vec![]));
        assert!(contract.on_transfer_complete(id, retry));
        assert_eq!(contract.get_job(id).unwrap().status, "ACCEPTED");
        assert_eq!(contract.get_escrowed_rewards(), NearToken::from_yoctonear(0));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.on_transfer_complete(id, retry))).is_err());
    }

    #[test]
    fn refund_failure_preserves_customer_entitlement_and_cannot_become_payout() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("customer.near", ACCEPTANCE, NearToken::from_yoctonear(0));
        contract.timeout(id);
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        callback_context("escrow.near", ACCEPTANCE, PromiseResult::Failed);
        assert!(!contract.on_transfer_complete(id, attempt));
        assert_eq!(contract.get_job(id).unwrap().status, "REFUND_READY");
        assert_eq!(contract.get_escrowed_rewards(), near(2));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            context("customer.near", 2_900, NearToken::from_yoctonear(0));
            contract.accept(id, HASH.to_string());
        })).is_err());
        context("anyone.near", 3_500, NearToken::from_yoctonear(0));
        contract.retry_transfer(id);
        let retry = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        callback_context("escrow.near", 3_500, PromiseResult::Successful(vec![]));
        assert!(contract.on_transfer_complete(id, retry));
        assert_eq!(contract.get_job(id).unwrap().status, "REFUNDED");
        assert_eq!(contract.get_escrowed_rewards(), NearToken::from_yoctonear(0));
    }

    #[test]
    fn actors_hash_and_deadline_boundaries_are_enforced() {
        let mut contract = setup();
        let id = open_job(&mut contract);
        context("worker.near", 500, NearToken::from_yoctonear(0));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.assign(id, account("worker.near")))).is_err());
        context("customer.near", 600, NearToken::from_yoctonear(0));
        contract.assign(id, account("worker.near"));
        context("worker.near", DECISION - 1, NearToken::from_yoctonear(0));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.submit(id, HASH.into()))).is_err());
        context("worker.near", DECISION, NearToken::from_yoctonear(0));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.submit(id, "ABC".into()))).is_err());
        contract.submit(id, HASH.into());
        context("customer.near", ACCEPTANCE, NearToken::from_yoctonear(0));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.accept(id, HASH.into()))).is_err());
    }

    #[test]
    fn creation_requires_reward_ordered_deadlines_and_storage_capacity() {
        context("deployer.near", 500, NearToken::from_millinear(500));
        assert!(std::panic::catch_unwind(|| ForecastJobs::new(account("resolver.near"))).is_err());

        let mut contract = setup();
        context("customer.near", 500, NearToken::from_yoctonear(0));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.create_job(DECISION, DELIVERY, ACCEPTANCE, DISPUTE))).is_err());
        context("customer.near", 500, near(1));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.create_job(DECISION, DECISION, ACCEPTANCE, DISPUTE))).is_err());

        for _ in 0..MAX_JOBS {
            context("customer.near", 500, near(1));
            contract.create_job(DECISION, DELIVERY, ACCEPTANCE, DISPUTE);
        }
        context("customer.near", 500, near(1));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.create_job(DECISION, DELIVERY, ACCEPTANCE, DISPUTE))).is_err());
        assert_eq!(contract.job_count(), MAX_JOBS);
    }

    #[test]
    fn submitted_hash_must_match_and_pending_payout_cannot_be_repeated_or_refunded() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("customer.near", 2_500, NearToken::from_yoctonear(0));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.accept(id, OTHER_HASH.into()))).is_err());
        contract.accept(id, HASH.into());
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.accept(id, HASH.into()))).is_err());
        context("anyone.near", ACCEPTANCE, NearToken::from_yoctonear(0));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.timeout(id))).is_err());
        callback_context("escrow.near", 2_600, PromiseResult::Failed);
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.on_transfer_complete(id, attempt + 1))).is_err());
        assert_eq!(contract.get_job(id).unwrap().pending_attempt_id, Some(attempt));
    }

    #[test]
    fn dispute_can_only_be_resolved_once_and_boundary_timeout_wins() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("customer.near", 2_500, NearToken::from_yoctonear(0));
        contract.dispute(id);
        context("resolver.near", DISPUTE, NearToken::from_yoctonear(0));
        contract.timeout(id);
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.resolve(id, true))).is_err());
        callback_context("escrow.near", DISPUTE, PromiseResult::Failed);
        assert!(!contract.on_transfer_complete(id, attempt));
        assert_eq!(contract.get_job(id).unwrap().status, "REFUND_READY");
    }

    #[test]
    fn open_cancel_and_assigned_timeout_refund_at_boundaries() {
        let mut contract = setup();
        let open_id = open_job(&mut contract);
        context("customer.near", DELIVERY - 1, NearToken::from_yoctonear(0));
        contract.cancel(open_id);
        assert_eq!(contract.get_job(open_id).unwrap().status, "REFUND_PENDING");

        let assigned_id = open_job(&mut contract);
        context("customer.near", 600, NearToken::from_yoctonear(0));
        contract.assign(assigned_id, account("worker.near"));
        context("anyone.near", DELIVERY, NearToken::from_yoctonear(0));
        contract.timeout(assigned_id);
        assert_eq!(contract.get_job(assigned_id).unwrap().status, "REFUND_PENDING");
    }

    #[test]
    fn dispute_resolver_and_timeout_race_have_one_outcome() {
        let mut contract = setup();
        let id = submitted_job(&mut contract);
        context("worker.near", 2_500, NearToken::from_yoctonear(0));
        contract.dispute(id);
        context("customer.near", 3_500, NearToken::from_yoctonear(0));
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.resolve(id, true))).is_err());
        context("resolver.near", 3_500, NearToken::from_yoctonear(0));
        contract.resolve(id, false);
        let attempt = contract.get_job(id).unwrap().pending_attempt_id.unwrap();
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| contract.timeout(id))).is_err());
        callback_context("escrow.near", 3_500, PromiseResult::Successful(vec![]));
        assert!(contract.on_transfer_complete(id, attempt));
        assert_eq!(contract.get_job(id).unwrap().status, "REFUNDED");
    }
}
