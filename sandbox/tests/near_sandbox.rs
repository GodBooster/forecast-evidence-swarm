use anyhow::{Context, Result};
use near_workspaces::{network::Sandbox, Account, Contract, Worker};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

const REWARD_NEAR: u128 = 2;
const RESERVE_NEAR: u128 = 1;
const CORE_SCENARIO: &str = "valid_wrong";

#[derive(serde::Serialize)]
struct Receipts {
    schema_version: &'static str,
    mode: &'static str,
    jobs: Vec<JobReceipt>,
}

#[derive(serde::Serialize)]
struct JobReceipt {
    job_id: String,
    artifact_sha256: String,
    customer: String,
    worker: String,
    status: &'static str,
    transaction_ids: Vec<String>,
}

fn tx_id(result: &near_workspaces::result::ExecutionFinalResult) -> String {
    result.outcome().transaction_hash.to_string()
}

fn hash_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn report_hash(report_path: &Path, scenario_name: &str) -> Result<String> {
    let report: Value = serde_json::from_slice(&std::fs::read(report_path)?)?;
    let scenario = report["scenarios"]
        .as_array()
        .context("core report has no scenarios")?
        .iter()
        .find(|case| case["scenario"] == scenario_name)
        .with_context(|| format!("core report has no {scenario_name} scenario"))?;
    let digest = scenario["delivery"]["sha256"]
        .as_str()
        .context("valid_wrong has no delivery sha256")?;
    anyhow::ensure!(
        digest.len() == 64 && digest.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()),
        "core artifact commitment is not lowercase SHA-256 hex"
    );
    Ok(digest.to_owned())
}

async fn account(root: &Account, name: &str) -> Result<Account> {
    Ok(root
        .create_subaccount(name)
        .initial_balance(near_workspaces::types::NearToken::from_near(30))
        .transact()
        .await?
        .into_result()
        .with_context(|| format!("create local account {name}"))?)
}

async fn block_time_ms(worker: &Worker<Sandbox>) -> Result<u64> {
    let block = worker.view_block().await?;
    Ok(block.timestamp() / 1_000_000)
}

async fn advance_until(worker: &Worker<Sandbox>, timestamp_ms: u64) -> Result<()> {
    for _ in 0..600 {
        if block_time_ms(worker).await? >= timestamp_ms {
            return Ok(());
        }
        worker.fast_forward(1).await?;
    }
    anyhow::bail!("sandbox did not reach requested block timestamp {timestamp_ms}");
}

fn deadlines(now_ms: u64, decision_ms: u64, delivery_ms: u64, acceptance_ms: u64) -> [u64; 4] {
    [
        now_ms + decision_ms,
        now_ms + delivery_ms,
        now_ms + acceptance_ms,
        now_ms + acceptance_ms + 30_000,
    ]
}

async fn create_job(
    customer: &Account,
    contract: &Contract,
    deadlines_ms: [u64; 4],
) -> Result<(u64, String)> {
    let result = customer
        .call(contract.id(), "create_job")
        .args_json(json!({
            "decision_deadline_ms": deadlines_ms[0],
            "delivery_deadline_ms": deadlines_ms[1],
            "acceptance_deadline_ms": deadlines_ms[2],
            "dispute_deadline_ms": deadlines_ms[3],
        }))
        .deposit(near_workspaces::types::NearToken::from_near(REWARD_NEAR))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(result.is_success(), "create_job failed: {result:#?}");
    let create_tx = tx_id(&result);
    let id = result.json::<u64>()?;
    Ok((id, create_tx))
}

async fn assign_and_submit(
    worker: &Worker<Sandbox>,
    contract: &Contract,
    customer: &Account,
    worker_account: &Account,
    deadlines_ms: [u64; 4],
    artifact_sha256: &str,
) -> Result<(u64, Vec<String>)> {
    let (job_id, create_tx) = create_job(customer, contract, deadlines_ms).await?;
    let assigned = customer
        .call(contract.id(), "assign")
        .args_json(json!({ "job_id": job_id, "worker": worker_account.id() }))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(assigned.is_success(), "assign failed: {assigned:#?}");
    let assign_tx = tx_id(&assigned);

    // NEAR Workspaces advances block timestamps with height. Move beyond the decision
    // boundary while remaining well before delivery.
    advance_until(worker, deadlines_ms[0]).await?;
    let submitted = worker_account
        .call(contract.id(), "submit")
        .args_json(json!({ "job_id": job_id, "artifact_sha256": artifact_sha256 }))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(submitted.is_success(), "submit failed: {submitted:#?}");
    Ok((job_id, vec![create_tx, assign_tx, tx_id(&submitted)]))
}

async fn status(contract: &Contract, job_id: u64) -> Result<String> {
    let job: Value = contract
        .view("get_job")
        .args_json(json!({ "id": job_id }))
        .await?
        .json()?;
    Ok(job["status"].as_str().context("job view has no status")?.to_owned())
}

async fn escrowed_yocto(contract: &Contract) -> Result<u128> {
    let value: String = contract.view("get_escrowed_rewards").await?.json()?;
    Ok(value.parse()?)
}

async fn balance_yocto(account: &Account) -> Result<u128> {
    Ok(account.view_account().await?.balance.as_yoctonear())
}

fn receipt(
    job_id: u64,
    artifact_sha256: &str,
    customer: &Account,
    worker: &Account,
    status: &'static str,
    transaction_ids: Vec<String>,
) -> JobReceipt {
    JobReceipt {
        job_id: job_id.to_string(),
        artifact_sha256: artifact_sha256.to_owned(),
        customer: customer.id().to_string(),
        worker: worker.id().to_string(),
        status,
        transaction_ids,
    }
}

fn output_path(env_name: &str, fallback: &str) -> PathBuf {
    std::env::var_os(env_name)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(fallback))
}

#[tokio::test]
async fn real_local_chain_escrow_and_transfer_recovery() -> Result<()> {
    let wasm_path = output_path(
        "FORECAST_CONTRACT_WASM",
        "contracts/forecast_jobs/target/wasm32-unknown-unknown/release/forecast_jobs.wasm",
    );
    let report_path = output_path("FORECAST_CORE_REPORT", "artifacts/demo/report.json");
    let receipts_path = output_path(
        "FORECAST_SANDBOX_RECEIPTS",
        "artifacts/demo/near-receipts.json",
    );
    let diagnostics_path = output_path(
        "FORECAST_SANDBOX_DIAGNOSTICS",
        "artifacts/demo/near-diagnostics.json",
    );
    let wasm = std::fs::read(&wasm_path)
        .with_context(|| format!("read contract wasm at {}", wasm_path.display()))?;
    let artifact_sha256 = report_hash(&report_path, CORE_SCENARIO)?;
    let refund_artifact_sha256 = report_hash(&report_path, "zero_successes")?;
    let contract_sha256 = hash_hex(&wasm);

    let worker = near_workspaces::sandbox().await.context("start local NEAR Sandbox")?;
    let root = worker.root_account().context("sandbox root account")?;
    let customer_paid = account(&root, "customer-paid").await?;
    let customer_timeout = account(&root, "customer-timeout").await?;
    let customer_retry = account(&root, "customer-retry").await?;
    let customer_refund_retry = account(&root, "customer-refund-retry").await?;
    let worker_paid = account(&root, "worker-paid").await?;
    let worker_timeout = account(&root, "worker-timeout").await?;
    let worker_retry = account(&root, "worker-retry").await?;
    let worker_refund_retry = account(&root, "worker-refund-retry").await?;
    let stranger = account(&root, "stranger").await?;
    let resolver = account(&root, "resolver").await?;

    let contract = worker.dev_deploy(&wasm).await.context("deploy forecast_jobs wasm")?;
    let init = contract
        .call("new")
        .args_json(json!({ "resolver": resolver.id() }))
        .deposit(near_workspaces::types::NearToken::from_near(RESERVE_NEAR))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(init.is_success(), "contract init failed: {init:#?}");

    let mut jobs = Vec::new();
    let mut traces = Vec::new();

    // Normal escrow: customer funds, assigns, worker binds the core artifact, and the
    // customer accepts. An unrelated caller and a duplicate settlement both fail.
    let paid_deadlines = deadlines(block_time_ms(&worker).await?, 10_000, 120_000, 180_000);
    let (paid_id, mut paid_txs) = assign_and_submit(
        &worker,
        &contract,
        &customer_paid,
        &worker_paid,
        paid_deadlines,
        &artifact_sha256,
    )
    .await?;
    let unauthorized = stranger
        .call(contract.id(), "accept")
        .args_json(json!({ "job_id": paid_id, "artifact_sha256": artifact_sha256 }))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(!unauthorized.is_success(), "wrong caller unexpectedly accepted payout");
    paid_txs.push(tx_id(&unauthorized));
    let paid_worker_balance_before = balance_yocto(&worker_paid).await?;
    let payout = customer_paid
        .call(contract.id(), "accept")
        .args_json(json!({ "job_id": paid_id, "artifact_sha256": artifact_sha256 }))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(payout.is_success(), "customer acceptance failed: {payout:#?}");
    paid_txs.push(tx_id(&payout));
    anyhow::ensure!(status(&contract, paid_id).await? == "ACCEPTED", "payout callback did not settle");
    let paid_worker_balance_after = balance_yocto(&worker_paid).await?;
    anyhow::ensure!(
        paid_worker_balance_after - paid_worker_balance_before == REWARD_NEAR * 10u128.pow(24),
        "worker did not receive exactly the escrowed reward"
    );
    let escrow_after_paid = escrowed_yocto(&contract).await?;
    anyhow::ensure!(escrow_after_paid == 0, "escrowed reward liability remains after paid job");
    let duplicate = customer_paid
        .call(contract.id(), "accept")
        .args_json(json!({ "job_id": paid_id, "artifact_sha256": artifact_sha256 }))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(!duplicate.is_success(), "duplicate acceptance unexpectedly succeeded");
    paid_txs.push(tx_id(&duplicate));
    jobs.push(receipt(paid_id, &artifact_sha256, &customer_paid, &worker_paid, "PAID", paid_txs));
    traces.push(json!({ "job_id": paid_id, "assertion": "acceptance transfers exact reward once; wrong caller and duplicate rejected", "wrong_caller_rejected": !unauthorized.is_success(), "duplicate_rejected": !duplicate.is_success(), "worker_balance_increase_yocto": (paid_worker_balance_after - paid_worker_balance_before).to_string(), "escrowed_rewards_after_job_yocto": escrow_after_paid.to_string(), "status": "ACCEPTED" }));

    // Separate deadline refund: even an already submitted artifact is refunded when
    // the customer does not accept by the acceptance deadline.
    let timeout_deadlines = deadlines(block_time_ms(&worker).await?, 10_000, 30_000, 60_000);
    let (timeout_id, mut timeout_txs) = assign_and_submit(
        &worker,
        &contract,
        &customer_timeout,
        &worker_timeout,
        timeout_deadlines,
        &refund_artifact_sha256,
    )
    .await?;
    advance_until(&worker, timeout_deadlines[2]).await?;
    let customer_balance_before_refund = balance_yocto(&customer_timeout).await?;
    let timeout = stranger
        .call(contract.id(), "timeout")
        .args_json(json!({ "job_id": timeout_id }))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(timeout.is_success(), "submitted job timeout failed: {timeout:#?}");
    timeout_txs.push(tx_id(&timeout));
    anyhow::ensure!(status(&contract, timeout_id).await? == "REFUNDED", "timeout refund callback did not settle");
    let customer_balance_after_refund = balance_yocto(&customer_timeout).await?;
    anyhow::ensure!(
        customer_balance_after_refund - customer_balance_before_refund == REWARD_NEAR * 10u128.pow(24),
        "customer did not receive exact timeout refund"
    );
    let escrow_after_refund = escrowed_yocto(&contract).await?;
    anyhow::ensure!(escrow_after_refund == 0, "escrowed reward liability remains after refunded job");
    jobs.push(receipt(timeout_id, &refund_artifact_sha256, &customer_timeout, &worker_timeout, "REFUNDED", timeout_txs));
    traces.push(json!({ "job_id": timeout_id, "assertion": "unaccepted submitted work refunds at acceptance deadline", "customer_balance_increase_yocto": (customer_balance_after_refund - customer_balance_before_refund).to_string(), "escrowed_rewards_after_job_yocto": escrow_after_refund.to_string(), "status": "REFUNDED" }));

    // Failed payout receipt: delete the local worker account after submission so the
    // transfer receipt fails; the contract must preserve PAYOUT_READY, then retry after
    // recreating the same local account ID.
    let retry_deadlines = deadlines(block_time_ms(&worker).await?, 10_000, 120_000, 180_000);
    let (retry_id, mut retry_txs) = assign_and_submit(
        &worker,
        &contract,
        &customer_retry,
        &worker_retry,
        retry_deadlines,
        &artifact_sha256,
    )
    .await?;
    worker_retry
        .delete_account(root.id())
        .await?
        .into_result()
        .context("delete ephemeral payout recipient")?;
    let failed_payout = customer_retry
        .call(contract.id(), "accept")
        .args_json(json!({ "job_id": retry_id, "artifact_sha256": artifact_sha256 }))
        .max_gas()
        .transact()
        .await?;
    retry_txs.push(tx_id(&failed_payout));
    anyhow::ensure!(
        !failed_payout.receipt_failures().is_empty(),
        "missing failed transfer receipt for deleted worker"
    );
    anyhow::ensure!(status(&contract, retry_id).await? == "PAYOUT_READY", "failed payout did not preserve worker entitlement");
    let worker_retry = account(&root, "worker-retry").await?;
    let worker_retry_balance_before = balance_yocto(&worker_retry).await?;
    let retried_payout = stranger
        .call(contract.id(), "retry_transfer")
        .args_json(json!({ "job_id": retry_id }))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(retried_payout.is_success(), "retry_transfer payout failed: {retried_payout:#?}");
    retry_txs.push(tx_id(&retried_payout));
    anyhow::ensure!(status(&contract, retry_id).await? == "ACCEPTED", "payout retry callback did not settle");
    let worker_retry_balance_after = balance_yocto(&worker_retry).await?;
    anyhow::ensure!(
        worker_retry_balance_after - worker_retry_balance_before == REWARD_NEAR * 10u128.pow(24),
        "payout retry did not transfer exactly the reward"
    );
    let escrow_after_payout_retry = escrowed_yocto(&contract).await?;
    anyhow::ensure!(escrow_after_payout_retry == 0, "reward liability remains after payout retry");
    traces.push(json!({ "job_id": retry_id, "assertion": "failed payout receipt preserves worker entitlement and permissionless retry pays once", "failed_transfer_receipts": failed_payout.receipt_failures().len(), "failed_transfer_status": "PAYOUT_READY", "retry_balance_increase_yocto": (worker_retry_balance_after - worker_retry_balance_before).to_string(), "escrowed_rewards_after_job_yocto": escrow_after_payout_retry.to_string(), "transaction_ids": retry_txs, "final_status": "ACCEPTED" }));

    // Failed refund receipt: remove the customer recipient, allow the submitted job to
    // time out, restore that account, then retry the immutable customer refund.
    let refund_deadlines = deadlines(block_time_ms(&worker).await?, 10_000, 30_000, 60_000);
    let (refund_id, mut refund_txs) = assign_and_submit(
        &worker,
        &contract,
        &customer_refund_retry,
        &worker_refund_retry,
        refund_deadlines,
        &artifact_sha256,
    )
    .await?;
    customer_refund_retry
        .delete_account(root.id())
        .await?
        .into_result()
        .context("delete ephemeral refund recipient")?;
    advance_until(&worker, refund_deadlines[2]).await?;
    let failed_refund = stranger
        .call(contract.id(), "timeout")
        .args_json(json!({ "job_id": refund_id }))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(failed_refund.is_success(), "timeout refund call failed: {failed_refund:#?}");
    refund_txs.push(tx_id(&failed_refund));
    anyhow::ensure!(
        !failed_refund.receipt_failures().is_empty(),
        "missing failed transfer receipt for deleted customer"
    );
    anyhow::ensure!(status(&contract, refund_id).await? == "REFUND_READY", "failed refund did not preserve customer entitlement");
    let customer_refund_retry = account(&root, "customer-refund-retry").await?;
    let customer_retry_balance_before = balance_yocto(&customer_refund_retry).await?;
    let retried_refund = stranger
        .call(contract.id(), "retry_transfer")
        .args_json(json!({ "job_id": refund_id }))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(retried_refund.is_success(), "retry_transfer refund failed: {retried_refund:#?}");
    refund_txs.push(tx_id(&retried_refund));
    anyhow::ensure!(status(&contract, refund_id).await? == "REFUNDED", "refund retry callback did not settle");
    let customer_retry_balance_after = balance_yocto(&customer_refund_retry).await?;
    anyhow::ensure!(
        customer_retry_balance_after - customer_retry_balance_before == REWARD_NEAR * 10u128.pow(24),
        "refund retry did not transfer exactly the reward"
    );
    let escrow_after_refund_retry = escrowed_yocto(&contract).await?;
    anyhow::ensure!(escrow_after_refund_retry == 0, "reward liability remains after refund retry");
    traces.push(json!({ "job_id": refund_id, "assertion": "failed refund receipt preserves customer entitlement and permissionless retry refunds once", "failed_transfer_receipts": failed_refund.receipt_failures().len(), "failed_transfer_status": "REFUND_READY", "retry_balance_increase_yocto": (customer_retry_balance_after - customer_retry_balance_before).to_string(), "escrowed_rewards_after_job_yocto": escrow_after_refund_retry.to_string(), "transaction_ids": refund_txs, "final_status": "REFUNDED" }));

    let final_escrow = escrowed_yocto(&contract).await?;
    anyhow::ensure!(final_escrow == 0, "local sandbox ended with outstanding reward liabilities");
    let job_count: u64 = contract.view("job_count").await?.json()?;
    anyhow::ensure!(job_count == 4, "expected four local jobs, found {job_count}");

    std::fs::create_dir_all(receipts_path.parent().unwrap_or_else(|| Path::new(".")))?;
    let receipt_doc = Receipts {
        schema_version: "forecast-near-receipts/v1",
        mode: "LOCAL_NEAR_SANDBOX",
        jobs,
    };
    std::fs::write(&receipts_path, serde_json::to_vec_pretty(&receipt_doc)?)?;
    let diagnostics = json!({
        "mode": "LOCAL_NEAR_SANDBOX",
        "network_mode": "local ephemeral NEAR sandbox",
        "runtime": "near-workspaces-rs 0.24.0 / near-sandbox",
        "contract_wasm_sha256": contract_sha256,
        "artifact_sha256": artifact_sha256,
        "contract_account": contract.id().to_string(),
        "contract_status": "deployed and initialized",
        "job_count": job_count,
        "final_escrowed_rewards_yocto": final_escrow.to_string(),
        "assertions": traces,
        "note": "Transaction hashes and statuses are from this local ephemeral chain; no Testnet or Mainnet was contacted."
    });
    std::fs::write(&diagnostics_path, serde_json::to_vec_pretty(&diagnostics)?)?;
    Ok(())
}

const YOCTO_PER_NEAR: u128 = 1_000_000_000_000_000_000_000_000;
/// Upper bound for the gas a customer may spend on its own `cancel` call. The refund
/// is credited to the signer of that transaction, so its balance delta is the reward
/// minus that transaction's gas; the contract-side liability check stays exact.
/// `max_gas()` prepays 1 PGas at a pessimistic price and the unused part returns in a
/// later refund receipt, so `cancel` attaches 50 Tgas and the balance is read only after
/// a few extra blocks (`SETTLE_BLOCKS`). The first 2026-11-08 run measured the balance
/// before that refund arrived and failed this check with a delta of about 1.0012 NEAR.
const CANCEL_GAS_TOLERANCE_YOCTO: u128 = 50_000_000_000_000_000_000_000; // 0.05 NEAR
const SETTLE_BLOCKS: u64 = 5;

async fn call_job(
    caller: &Account,
    contract: &Contract,
    method: &str,
    args: Value,
) -> Result<near_workspaces::result::ExecutionFinalResult> {
    Ok(caller
        .call(contract.id(), method)
        .args_json(args)
        .max_gas()
        .transact()
        .await?)
}

/// Dispute, resolver decision, dispute timeout and cancellation on a separate local
/// chain. Writes only its own diagnostics file; the knowledge-export receipts produced
/// by `real_local_chain_escrow_and_transfer_recovery` are not affected.
#[tokio::test]
async fn real_local_chain_dispute_resolve_timeout_and_cancel() -> Result<()> {
    let wasm_path = output_path(
        "FORECAST_CONTRACT_WASM",
        "contracts/forecast_jobs/target/wasm32-unknown-unknown/release/forecast_jobs.wasm",
    );
    let report_path = output_path("FORECAST_CORE_REPORT", "artifacts/demo/report.json");
    let diagnostics_path = output_path(
        "FORECAST_SANDBOX_DISPUTE_DIAGNOSTICS",
        "artifacts/demo/near-dispute-cancel-diagnostics.json",
    );
    let wasm = std::fs::read(&wasm_path)
        .with_context(|| format!("read contract wasm at {}", wasm_path.display()))?;
    let artifact_sha256 = report_hash(&report_path, CORE_SCENARIO)?;
    let reward = REWARD_NEAR * YOCTO_PER_NEAR;

    let worker = near_workspaces::sandbox().await.context("start local NEAR Sandbox")?;
    let root = worker.root_account().context("sandbox root account")?;
    let customer = account(&root, "customer-dispute").await?;
    let worker_account = account(&root, "worker-dispute").await?;
    let stranger = account(&root, "stranger").await?;
    let resolver = account(&root, "resolver").await?;

    let contract = worker.dev_deploy(&wasm).await.context("deploy forecast_jobs wasm")?;
    let init = contract
        .call("new")
        .args_json(json!({ "resolver": resolver.id() }))
        .deposit(near_workspaces::types::NearToken::from_near(RESERVE_NEAR))
        .max_gas()
        .transact()
        .await?;
    anyhow::ensure!(init.is_success(), "contract init failed: {init:#?}");

    let mut traces = Vec::new();

    // A. Customer disputes; only the named resolver may decide; it pays the worker once.
    let a_deadlines = deadlines(block_time_ms(&worker).await?, 10_000, 120_000, 180_000);
    let (a_id, mut a_txs) = assign_and_submit(
        &worker, &contract, &customer, &worker_account, a_deadlines, &artifact_sha256,
    )
    .await?;
    let premature = call_job(&resolver, &contract, "resolve", json!({ "job_id": a_id, "pay_worker": true })).await?;
    anyhow::ensure!(!premature.is_success(), "resolver decided a job that was not disputed");
    a_txs.push(tx_id(&premature));
    let stranger_dispute = call_job(&stranger, &contract, "dispute", json!({ "job_id": a_id })).await?;
    anyhow::ensure!(!stranger_dispute.is_success(), "stranger unexpectedly opened a dispute");
    a_txs.push(tx_id(&stranger_dispute));
    let disputed = call_job(&customer, &contract, "dispute", json!({ "job_id": a_id })).await?;
    anyhow::ensure!(disputed.is_success(), "customer dispute failed: {disputed:#?}");
    a_txs.push(tx_id(&disputed));
    anyhow::ensure!(status(&contract, a_id).await? == "DISPUTED", "job did not enter DISPUTED");
    let accept_disputed = call_job(&customer, &contract, "accept", json!({ "job_id": a_id, "artifact_sha256": artifact_sha256 })).await?;
    anyhow::ensure!(!accept_disputed.is_success(), "disputed job was accepted directly");
    a_txs.push(tx_id(&accept_disputed));
    let stranger_resolve = call_job(&stranger, &contract, "resolve", json!({ "job_id": a_id, "pay_worker": false })).await?;
    anyhow::ensure!(!stranger_resolve.is_success(), "stranger unexpectedly resolved a dispute");
    a_txs.push(tx_id(&stranger_resolve));
    let customer_resolve = call_job(&customer, &contract, "resolve", json!({ "job_id": a_id, "pay_worker": false })).await?;
    anyhow::ensure!(!customer_resolve.is_success(), "customer unexpectedly resolved its own dispute");
    a_txs.push(tx_id(&customer_resolve));
    let a_before = balance_yocto(&worker_account).await?;
    let resolved_pay = call_job(&resolver, &contract, "resolve", json!({ "job_id": a_id, "pay_worker": true })).await?;
    anyhow::ensure!(resolved_pay.is_success(), "resolver payout failed: {resolved_pay:#?}");
    a_txs.push(tx_id(&resolved_pay));
    anyhow::ensure!(status(&contract, a_id).await? == "ACCEPTED", "resolver payout callback did not settle");
    let a_after = balance_yocto(&worker_account).await?;
    anyhow::ensure!(a_after - a_before == reward, "worker did not receive exactly the reward after resolution");
    let second_resolve = call_job(&resolver, &contract, "resolve", json!({ "job_id": a_id, "pay_worker": false })).await?;
    anyhow::ensure!(!second_resolve.is_success(), "second resolution unexpectedly succeeded");
    a_txs.push(tx_id(&second_resolve));
    let a_timeout = call_job(&stranger, &contract, "timeout", json!({ "job_id": a_id })).await?;
    anyhow::ensure!(!a_timeout.is_success(), "settled job unexpectedly refunded by timeout");
    a_txs.push(tx_id(&a_timeout));
    let a_escrow = escrowed_yocto(&contract).await?;
    anyhow::ensure!(a_escrow == 0, "liability remains after resolver payout");
    traces.push(json!({ "job_id": a_id, "assertion": "customer dispute; resolver-only decision pays worker exactly once", "premature_resolve_rejected": true, "stranger_dispute_rejected": true, "accept_while_disputed_rejected": true, "stranger_resolve_rejected": true, "customer_resolve_rejected": true, "second_resolve_rejected": true, "timeout_after_settlement_rejected": true, "worker_balance_increase_yocto": (a_after - a_before).to_string(), "escrowed_rewards_after_job_yocto": a_escrow.to_string(), "transaction_ids": a_txs, "final_status": "ACCEPTED" }));

    // B. Worker disputes; resolver refunds the customer exactly.
    let b_deadlines = deadlines(block_time_ms(&worker).await?, 10_000, 120_000, 180_000);
    let (b_id, mut b_txs) = assign_and_submit(
        &worker, &contract, &customer, &worker_account, b_deadlines, &artifact_sha256,
    )
    .await?;
    let worker_dispute = call_job(&worker_account, &contract, "dispute", json!({ "job_id": b_id })).await?;
    anyhow::ensure!(worker_dispute.is_success(), "worker dispute failed: {worker_dispute:#?}");
    b_txs.push(tx_id(&worker_dispute));
    let b_before = balance_yocto(&customer).await?;
    let resolved_refund = call_job(&resolver, &contract, "resolve", json!({ "job_id": b_id, "pay_worker": false })).await?;
    anyhow::ensure!(resolved_refund.is_success(), "resolver refund failed: {resolved_refund:#?}");
    b_txs.push(tx_id(&resolved_refund));
    anyhow::ensure!(status(&contract, b_id).await? == "REFUNDED", "resolver refund callback did not settle");
    let b_after = balance_yocto(&customer).await?;
    anyhow::ensure!(b_after - b_before == reward, "customer did not receive exactly the reward after resolution");
    let b_escrow = escrowed_yocto(&contract).await?;
    anyhow::ensure!(b_escrow == 0, "liability remains after resolver refund");
    traces.push(json!({ "job_id": b_id, "assertion": "worker dispute; resolver refund returns exactly the reward to the customer", "customer_balance_increase_yocto": (b_after - b_before).to_string(), "escrowed_rewards_after_job_yocto": b_escrow.to_string(), "transaction_ids": b_txs, "final_status": "REFUNDED" }));

    // C. Silent resolver: after the dispute deadline the resolver can no longer decide and
    // anyone can trigger the customer refund.
    let c_deadlines = deadlines(block_time_ms(&worker).await?, 10_000, 30_000, 60_000);
    let (c_id, mut c_txs) = assign_and_submit(
        &worker, &contract, &customer, &worker_account, c_deadlines, &artifact_sha256,
    )
    .await?;
    let c_dispute = call_job(&customer, &contract, "dispute", json!({ "job_id": c_id })).await?;
    anyhow::ensure!(c_dispute.is_success(), "dispute before timeout failed: {c_dispute:#?}");
    c_txs.push(tx_id(&c_dispute));
    let early_timeout = call_job(&stranger, &contract, "timeout", json!({ "job_id": c_id })).await?;
    anyhow::ensure!(!early_timeout.is_success(), "disputed job refunded before the dispute deadline");
    c_txs.push(tx_id(&early_timeout));
    advance_until(&worker, c_deadlines[3]).await?;
    let late_resolve = call_job(&resolver, &contract, "resolve", json!({ "job_id": c_id, "pay_worker": true })).await?;
    anyhow::ensure!(!late_resolve.is_success(), "resolver decided after the dispute deadline");
    c_txs.push(tx_id(&late_resolve));
    let c_before = balance_yocto(&customer).await?;
    let dispute_timeout = call_job(&stranger, &contract, "timeout", json!({ "job_id": c_id })).await?;
    anyhow::ensure!(dispute_timeout.is_success(), "dispute timeout refund failed: {dispute_timeout:#?}");
    c_txs.push(tx_id(&dispute_timeout));
    anyhow::ensure!(status(&contract, c_id).await? == "REFUNDED", "dispute timeout callback did not settle");
    let c_after = balance_yocto(&customer).await?;
    anyhow::ensure!(c_after - c_before == reward, "customer did not receive exactly the reward at dispute timeout");
    let c_escrow = escrowed_yocto(&contract).await?;
    anyhow::ensure!(c_escrow == 0, "liability remains after dispute timeout");
    traces.push(json!({ "job_id": c_id, "assertion": "silent resolver: refund only after dispute deadline; late resolution rejected", "early_timeout_rejected": true, "late_resolve_rejected": true, "customer_balance_increase_yocto": (c_after - c_before).to_string(), "escrowed_rewards_after_job_yocto": c_escrow.to_string(), "transaction_ids": c_txs, "final_status": "REFUNDED" }));

    // D. Cancellation of an open job by its customer only, exactly once.
    let d_deadlines = deadlines(block_time_ms(&worker).await?, 10_000, 120_000, 180_000);
    let (d_id, d_create) = create_job(&customer, &contract, d_deadlines).await?;
    let mut d_txs = vec![d_create];
    let escrow_open = escrowed_yocto(&contract).await?;
    anyhow::ensure!(escrow_open == reward, "open job liability is not exactly the reward");
    let stranger_cancel = call_job(&stranger, &contract, "cancel", json!({ "job_id": d_id })).await?;
    anyhow::ensure!(!stranger_cancel.is_success(), "stranger unexpectedly cancelled a job");
    d_txs.push(tx_id(&stranger_cancel));
    // Let gas refunds of the customer's earlier transactions land before measuring.
    worker.fast_forward(SETTLE_BLOCKS).await?;
    let d_before = balance_yocto(&customer).await?;
    let cancelled = customer
        .call(contract.id(), "cancel")
        .args_json(json!({ "job_id": d_id }))
        .gas(near_workspaces::types::Gas::from_tgas(50))
        .transact()
        .await?;
    anyhow::ensure!(cancelled.is_success(), "customer cancel failed: {cancelled:#?}");
    d_txs.push(tx_id(&cancelled));
    anyhow::ensure!(status(&contract, d_id).await? == "REFUNDED", "cancel refund callback did not settle");
    worker.fast_forward(SETTLE_BLOCKS).await?;
    let d_after = balance_yocto(&customer).await?;
    let d_delta = d_after as i128 - d_before as i128;
    anyhow::ensure!(
        d_delta <= reward as i128 && d_delta >= (reward - CANCEL_GAS_TOLERANCE_YOCTO) as i128,
        "cancel refund outside [reward - gas tolerance, reward]: {d_delta}"
    );
    let d_escrow = escrowed_yocto(&contract).await?;
    anyhow::ensure!(d_escrow == 0, "liability remains after cancellation");
    let second_cancel = call_job(&customer, &contract, "cancel", json!({ "job_id": d_id })).await?;
    anyhow::ensure!(!second_cancel.is_success(), "second cancel unexpectedly succeeded");
    d_txs.push(tx_id(&second_cancel));
    let assign_cancelled = call_job(&customer, &contract, "assign", json!({ "job_id": d_id, "worker": worker_account.id() })).await?;
    anyhow::ensure!(!assign_cancelled.is_success(), "cancelled job was assigned");
    d_txs.push(tx_id(&assign_cancelled));
    traces.push(json!({ "job_id": d_id, "assertion": "customer-only cancel of an open job refunds once; contract liability drops by exactly the reward", "stranger_cancel_rejected": true, "second_cancel_rejected": true, "assign_after_cancel_rejected": true, "escrowed_rewards_while_open_yocto": escrow_open.to_string(), "customer_balance_delta_including_own_gas_yocto": d_delta.to_string(), "gas_tolerance_yocto": CANCEL_GAS_TOLERANCE_YOCTO.to_string(), "escrowed_rewards_after_job_yocto": d_escrow.to_string(), "transaction_ids": d_txs, "final_status": "REFUNDED" }));

    // E. An assigned job can no longer be cancelled; it settles by the delivery timeout.
    let e_deadlines = deadlines(block_time_ms(&worker).await?, 10_000, 30_000, 60_000);
    let (e_id, e_create) = create_job(&customer, &contract, e_deadlines).await?;
    let mut e_txs = vec![e_create];
    let e_assign = call_job(&customer, &contract, "assign", json!({ "job_id": e_id, "worker": worker_account.id() })).await?;
    anyhow::ensure!(e_assign.is_success(), "assign failed: {e_assign:#?}");
    e_txs.push(tx_id(&e_assign));
    let e_cancel = call_job(&customer, &contract, "cancel", json!({ "job_id": e_id })).await?;
    anyhow::ensure!(!e_cancel.is_success(), "assigned job was cancelled");
    e_txs.push(tx_id(&e_cancel));
    advance_until(&worker, e_deadlines[1]).await?;
    let e_before = balance_yocto(&customer).await?;
    let e_timeout = call_job(&stranger, &contract, "timeout", json!({ "job_id": e_id })).await?;
    anyhow::ensure!(e_timeout.is_success(), "delivery timeout failed: {e_timeout:#?}");
    e_txs.push(tx_id(&e_timeout));
    anyhow::ensure!(status(&contract, e_id).await? == "REFUNDED", "delivery timeout callback did not settle");
    let e_after = balance_yocto(&customer).await?;
    anyhow::ensure!(e_after - e_before == reward, "customer did not receive exactly the reward at delivery timeout");
    traces.push(json!({ "job_id": e_id, "assertion": "assigned job cannot be cancelled; undelivered work refunds exactly at the delivery deadline", "cancel_after_assign_rejected": true, "customer_balance_increase_yocto": (e_after - e_before).to_string(), "transaction_ids": e_txs, "final_status": "REFUNDED" }));

    let final_escrow = escrowed_yocto(&contract).await?;
    anyhow::ensure!(final_escrow == 0, "local sandbox ended with outstanding reward liabilities");
    let job_count: u64 = contract.view("job_count").await?.json()?;
    anyhow::ensure!(job_count == 5, "expected five local jobs, found {job_count}");

    std::fs::create_dir_all(diagnostics_path.parent().unwrap_or_else(|| Path::new(".")))?;
    let diagnostics = json!({
        "mode": "LOCAL_NEAR_SANDBOX",
        "network_mode": "local ephemeral NEAR sandbox",
        "runtime": "near-workspaces-rs 0.24.0 / near-sandbox",
        "contract_wasm_sha256": hash_hex(&wasm),
        "artifact_sha256": artifact_sha256,
        "contract_account": contract.id().to_string(),
        "job_count": job_count,
        "final_escrowed_rewards_yocto": final_escrow.to_string(),
        "assertions": traces,
        "note": "Dispute/resolve/timeout/cancel paths on a local ephemeral chain; no receipts are exported for publication. No Testnet or Mainnet was contacted."
    });
    std::fs::write(&diagnostics_path, serde_json::to_vec_pretty(&diagnostics)?)?;
    Ok(())
}
