import json
import yaml
import random
import os
from typing import Dict, List, Tuple

RPC_URL = "http://80.66.85.98:26657"

TOPIC_CONFIGS = {
    1: {"window": 12, "interval": (15, 25), "workers_percent": 12},
    3: {"window": 12, "interval": (15, 25), "workers_percent": 11},
    5: {"window": 12, "interval": (15, 25), "workers_percent": 11},
    7: {"window": 24, "interval": (50, 70), "workers_percent": 11},
    8: {"window": 24, "interval": (50, 70), "workers_percent": 11},
    9: {"window": 24, "interval": (50, 70), "workers_percent": 11},
    2: {"window": 60, "interval": (90, 120), "workers_percent": 11},
    4: {"window": 60, "interval": (90, 120), "workers_percent": 11},
    6: {"window": 60, "interval": (90, 120), "workers_percent": 11}
}

# Group topics by similar window sizes
TOPIC_GROUPS = [
    [1, 3, 5],  # 12-hour window
    [7, 8, 9],  # 24-hour window
    [2, 4, 6]   # 60-hour window
]

def calculate_worker_distribution(total_workers: int) -> Dict[int, int]:
    distribution = {}
    remaining_workers = total_workers

    for topic_id, config in TOPIC_CONFIGS.items():
        if config["workers_percent"] > 0:
            workers = int(total_workers * config["workers_percent"] / 100)
            distribution[topic_id] = workers
            remaining_workers -= workers

    high_priority_topics = [1, 3, 5]
    while remaining_workers > 0:
        for topic_id in high_priority_topics:
            if remaining_workers > 0:
                distribution[topic_id] = distribution.get(topic_id, 0) + 1
                remaining_workers -= 1

    return distribution

def generate_offsets(num_workers: int, window: int) -> List[int]:
    if num_workers <= window:
        return list(range(num_workers))

    offsets = []
    workers_per_slot = num_workers / window
    for i in range(num_workers):
        offset = int(i / workers_per_slot) % window
        offsets.append(offset)
    random.shuffle(offsets)
    return offsets

def get_random_topics_from_groups() -> List[int]:
    return [random.choice(group) for group in TOPIC_GROUPS]

def main():
    with open('seed_phrases.txt', 'r') as f:
        seed_phrases = [line.strip() for line in f if line.strip()]

    total_workers = len(seed_phrases)
    config = {"workers": []}
    docker_compose = {'version': '3', 'services': {}}

    worker_template = {
        'image': 'alloranetwork/allora-offchain-node:v0.5.1',
        'depends_on': {'inference': {'condition': 'service_healthy'}},
        'deploy': {'resources': {'limits': {}}}
    }

    for worker_idx in range(total_workers):
        if worker_idx >= len(seed_phrases):
            break

        # Get three random topics (one from each group) for this worker
        worker_topics = get_random_topics_from_groups()

        # Create worker configuration with multiple topics
        worker_config = {
            "wallet": {
                "addressKeyName": f"WALLET_{random.randint(1000, 9999)}",
                "addressRestoreMnemonic": seed_phrases[worker_idx],
                "alloraHomeDir": f"./root/.allorad_{worker_idx + 1}",
                "gas": "auto",
                "gasAdjustment": 1.5,
                "gasPrices": 10,
                "maxFees": 2500000,
                "nodeRpc": RPC_URL,
                "maxRetries": 2,
                "retryDelay": 3,
                "accountSequenceRetryDelay": 5,
                "submitTx": True,
                "blockDurationEstimated": 5,
                "windowCorrectionFactor": 0.8
            },
            "worker": []
        }

        # Add three topics to this worker
        for topic_id in worker_topics:
            topic_config = TOPIC_CONFIGS[topic_id]
            min_interval, max_interval = topic_config["interval"]
            
            topic_worker_config = {
                "topicId": topic_id,
                "inferenceEntrypointName": "api-worker-reputer",
                "loopSeconds": random.randint(min_interval, max_interval),
                "parameters": {
                    "InferenceEndpoint": f"http://inference:8000/inference/{topic_id}?worker_id={worker_idx + 1}"
                }
            }
            worker_config["worker"].append(topic_worker_config)

        config['workers'].append(worker_config)
        docker_compose['services'][f'worker{worker_idx + 1}'] = {
            **worker_template,
            'container_name': f'allora-worker{worker_idx + 1}',
            'environment': [
                f'ALLORA_OFFCHAIN_NODE_CONFIG_JSON=${{WORKER{worker_idx + 1}_CONFIG}}',
                f'WORKER_ID={worker_idx + 1}'
            ]
        }

    docker_compose['services']['inference'] = {
        'build': '.',
        'command': 'python -u /app/app.py',
        'container_name': 'allora-inference',
        'env_file': ['.env'],
        'environment': [f'RPC_URL={RPC_URL}'],
        'healthcheck': {
            'test': ['CMD', 'curl', '-f', 'http://localhost:8000/health'],
            'interval': '30s',
            'timeout': '20s',
            'retries': 10,
            'start_period': '300s'
        },
        'ports': ['8000:8000'],
        'volumes': [
            './inference-data:/app/data',
            './logs:/app/logs'
        ],
        'restart': 'always',
        'deploy': {
            'resources': {'limits': {}}
        }
    }

    with open('multi_worker_config.json', 'w') as f:
        json.dump(config, f, indent=2)

    with open('docker-compose.yml', 'w') as f:
        yaml.dump(docker_compose, f)

    env_content = ["TOKENS=R", "MODEL=SVR", f"RPC_URL={RPC_URL}"]
    for i, worker in enumerate(config['workers'], 1):
        env_content.append(f"WORKER{i}_CONFIG='{json.dumps(worker)}'")

    with open('.env', 'w') as f:
        f.write('\n'.join(env_content))

    print(f"\nTotal workers: {total_workers}")
    
    # Create a summary of topic distribution
    topic_count = {i: 0 for i in TOPIC_CONFIGS.keys()}
    for worker in config['workers']:
        for topic_config in worker['worker']:
            topic_count[topic_config['topicId']] += 1
    
    print("\nTopic distribution:")
    for topic_id, count in topic_count.items():
        print(f"Topic {topic_id}: {count} workers ({count/total_workers*100:.1f}%)")
    
    print("\nWorker configuration summary:")
    for i, worker in enumerate(config['workers'], 1):
        topics = [t["topicId"] for t in worker["worker"]]
        print(f"Worker {i}: Topics {topics}")

if __name__ == "__main__":
    main()