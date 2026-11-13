# NEAR testnet run: `escrow.forecast-evidence-swarm.testnet`

Synthetic orders, testnet NEAR only. Every line below can be re-checked against the chain; `chain-snapshot.json` is the contract state this summary was built from (block 277503826, 2026-11-13T11:28:09Z, read through one RPC node).

- Contract: [escrow.forecast-evidence-swarm.testnet](https://testnet.nearblocks.io/address/escrow.forecast-evidence-swarm.testnet)
- Resolver: `resolver.forecast-evidence-swarm.testnet`
- Jobs created: 6
- Escrowed rewards after the run: 0 yoctoNEAR
- Per-job storage deposits kept by the contract: 60000000000000000000000 yoctoNEAR

**What this run is.** Three jobs recorded on 2026-11-13 while filming the demo video. Job 5 is the one shown
in the video end to end: the customer funds it, the worker agent submits, a one-character edit of the delivery
is refused by the customer's check (`DO NOT ACCEPT`, nothing signed), the genuine delivery passes
(`SAFE TO ACCEPT`) and is accepted and paid, and publication consent is recorded. Jobs 3 and 4 are rehearsals
from the same afternoon; they were settled so that no reward stays escrowed. The rejected tampered copy never
reached the chain by design, so it has no transaction here — reproduce it with the command in the delivery
check below. The earlier run (refund by timeout, dispute resolved by the resolver) is in
[`../testnet-2026-11-09`](../testnet-2026-11-09).

**Re-check any delivery against the chain, without keys:**

```
python3 -m forecast_swarm.verify --bundle docs/evidence/testnet-2026-11-13/deliveries/job5.json \
  --near-contract escrow.forecast-evidence-swarm.testnet --job-id 5 \
  --expect-order-sha256 d832e12efe1d10612ff57fbbad6adae2f1d471b06870d92ddc018268b1189e36
```

## Job 3 (`fes-live-1`)

- Final status: **ACCEPTED** → receipt `PAID`
- Customer `customer.forecast-evidence-swarm.testnet`, worker `worker.forecast-evidence-swarm.testnet`, reward 100000000000000000000000 yoctoNEAR
- Order hash `881ac76e7b4ef974e71060a80eb1050b6192a8f78aac5a67a0c13e088935c1f4`
- Delivery hash `b7d10d265d2e6b726d6f60243c43afd56b5e68ec0e76d534a1122338605d2024`
- Publication consent on chain: `false`

| Step | Signer | Key | Transaction |
|---|---|---|---|
| `create_job` | `customer.forecast-evidence-swarm.testnet` | keychain | [9h3eHkfRUPcSQztyPcUoSEpECZVPifajUQ6StBptF9kZ](https://testnet.nearblocks.io/txns/9h3eHkfRUPcSQztyPcUoSEpECZVPifajUQ6StBptF9kZ) |
| `assign` | `customer.forecast-evidence-swarm.testnet` | keychain | [FmWRb6mTD9xrxnt52qy6fe6GuQG8druHWLag43ZJ95vC](https://testnet.nearblocks.io/txns/FmWRb6mTD9xrxnt52qy6fe6GuQG8druHWLag43ZJ95vC) |
| `submit` | `worker.forecast-evidence-swarm.testnet` | legacy-keychain | [G4wJygEDdbVdtDiAzKsrH9ebhQq2bzqjhsvy7EjGM7MV](https://testnet.nearblocks.io/txns/G4wJygEDdbVdtDiAzKsrH9ebhQq2bzqjhsvy7EjGM7MV) |
| `accept` | `customer.forecast-evidence-swarm.testnet` | keychain | [GZMbuLNtQyRC4CajPN7V7NoPpPxW2C5Y1kZ5F5TgsaRF](https://testnet.nearblocks.io/txns/GZMbuLNtQyRC4CajPN7V7NoPpPxW2C5Y1kZ5F5TgsaRF) |

## Job 4 (`fes-live-2`)

- Final status: **ACCEPTED** → receipt `PAID`
- Customer `customer.forecast-evidence-swarm.testnet`, worker `worker.forecast-evidence-swarm.testnet`, reward 100000000000000000000000 yoctoNEAR
- Order hash `cdc6fa563a1ac58b19d11f3ba15717e7673184afd1600e7a9a6a9b61178b444f`
- Delivery hash `808e19c91fd1b72798fe41302c99370c4a2717353c514859807eaf3b6b54ab9e`
- Publication consent on chain: `false`

| Step | Signer | Key | Transaction |
|---|---|---|---|
| `create_job` | `customer.forecast-evidence-swarm.testnet` | keychain | [5JyjsZ2TZ8ncTQDd4EyLVqVLiH2PqZHAQKKucsKVHMnh](https://testnet.nearblocks.io/txns/5JyjsZ2TZ8ncTQDd4EyLVqVLiH2PqZHAQKKucsKVHMnh) |
| `assign` | `customer.forecast-evidence-swarm.testnet` | keychain | [F7QPectKX8FsGmz8q7HND4xUB2biA71u2pEqqfjqoiYd](https://testnet.nearblocks.io/txns/F7QPectKX8FsGmz8q7HND4xUB2biA71u2pEqqfjqoiYd) |
| `submit` | `worker.forecast-evidence-swarm.testnet` | legacy-keychain | [8qW9En9K23opXLmhedoYLfGiJ1oQsyRPXU9V4A7ri6nw](https://testnet.nearblocks.io/txns/8qW9En9K23opXLmhedoYLfGiJ1oQsyRPXU9V4A7ri6nw) |
| `accept` | `customer.forecast-evidence-swarm.testnet` | keychain | [4vMLEwiMuXzUkUWoE8X7Ce2x5ZVS6KjPJndhAvMbw9bU](https://testnet.nearblocks.io/txns/4vMLEwiMuXzUkUWoE8X7Ce2x5ZVS6KjPJndhAvMbw9bU) |

## Job 5 (`fes-live-1`)

- Final status: **ACCEPTED** → receipt `PAID`
- Customer `customer.forecast-evidence-swarm.testnet`, worker `worker.forecast-evidence-swarm.testnet`, reward 100000000000000000000000 yoctoNEAR
- Order hash `d832e12efe1d10612ff57fbbad6adae2f1d471b06870d92ddc018268b1189e36`
- Delivery hash `a0fbc6345f72e6516356b5ac98341e4dba353b395ee7f24e4be451b410315247`
- Publication consent on chain: `true`

| Step | Signer | Key | Transaction |
|---|---|---|---|
| `create_job` | `customer.forecast-evidence-swarm.testnet` | keychain | [67izaoTckBwUNssgsT9wRoX3fTPGdJvaRsTD3XEHbcNW](https://testnet.nearblocks.io/txns/67izaoTckBwUNssgsT9wRoX3fTPGdJvaRsTD3XEHbcNW) |
| `assign` | `customer.forecast-evidence-swarm.testnet` | keychain | [7CeP8aPrgsk66jVBwq35waNtsmPVhEZnBT7VrWHipWYf](https://testnet.nearblocks.io/txns/7CeP8aPrgsk66jVBwq35waNtsmPVhEZnBT7VrWHipWYf) |
| `submit` | `worker.forecast-evidence-swarm.testnet` | legacy-keychain | [9DseaS3NvGud1Uc8BW65XnMgYH8kTT3Qc11EjZjKozZv](https://testnet.nearblocks.io/txns/9DseaS3NvGud1Uc8BW65XnMgYH8kTT3Qc11EjZjKozZv) |
| `accept` | `customer.forecast-evidence-swarm.testnet` | keychain | [DgyABXXiQcmyXmdsYWd9xkidNbwh98JehbeUTNXGhnZs](https://testnet.nearblocks.io/txns/DgyABXXiQcmyXmdsYWd9xkidNbwh98JehbeUTNXGhnZs) |
| `consent_publication` | `customer.forecast-evidence-swarm.testnet` | keychain | [4F6ZkSVNFcnWaLPEk12yqHuas98WZM95Q5hxeZ8LEVhr](https://testnet.nearblocks.io/txns/4F6ZkSVNFcnWaLPEk12yqHuas98WZM95Q5hxeZ8LEVhr) |
