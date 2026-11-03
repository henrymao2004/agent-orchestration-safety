FROM trustfork-agents:tf-three-harnesses-v1
WORKDIR /workspace
COPY workspace/ /workspace/
COPY home/ /root/
RUN git init && git config user.email 'test@example.com' && git config user.name 'Test User' && git add . && git commit -m 'Initial commit'
