#!/bin/bash
# automated Alibaba Cloud ECS Deployment Script

echo "=== Starting Qwen Autopilot Ops Deployment ==="

# 1. Update package index
sudo apt-get update -y

# 2. Install Docker if it is not already installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker CE..."
    sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io
    sudo systemctl start docker
    sudo systemctl enable docker
    echo "Docker installed successfully."
else
    echo "Docker is already installed."
fi

# 3. Stop and remove existing container if running
if [ "$(sudo docker ps -aq -f name=qwen-ops)" ]; then
    echo "Stopping and removing existing container 'qwen-ops'..."
    sudo docker stop qwen-ops
    sudo docker rm qwen-ops
fi

# 4. Build Docker Image
echo "Building Qwen Autopilot Ops Docker Image..."
sudo docker build -t qwen-autopilot-ops:latest .

# 5. Run the Container
echo "Starting container 'qwen-ops' on port 8000..."
# Running container in detached mode with restart policy
sudo docker run -d \
  --name qwen-ops \
  -p 8000:8000 \
  --restart always \
  qwen-autopilot-ops:latest

echo "=== Deployment Completed Successfully! ==="
echo "The application is running at: http://<your-ecs-public-ip>:8000"
