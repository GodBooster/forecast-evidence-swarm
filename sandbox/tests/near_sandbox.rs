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
    result.raw_outcome().transaction.hash.to_string()
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
    Ok(block.header.timestamp_nanosec / 1_000_000)
}

async fn advance_until(worker: &Worker<Sandbox>, timestamp_ms: u64) -> Result<()> {
    for _ in 0..180 {
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
    let id = result.json::<u64>()?;
    Ok((id, tx_id(&result)))
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
    worker
        .delete_account(worker_retry.id(), worker_retry.signer(), root.id())
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
    worker
        .delete_account(customer_refund_retry.id(), customer_refund_retry.signer(), root.id())
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
