# Run
Create a tmux session for the controller, agent, and client. Run the following commands in the corresponding session.
1. run `python3 -m controller.controller --port 50051`
2. run `python3.11 -m agent.agent -a node1 -c localhost:50051` (this one needs python 3.11+)
2. run `python3 -m client.client node1 www.google.com`

# tmux
Currently all tmux sessions are running. To test, `tmux attach-session -t client` and run `python3 client.py`. Wait ~5 seconds and the output will appear in stdout. Note, there seems to be a bug causing the receive times for ICMP replies to be inflated by up to 50 milliseconds. This could be related to the datetime python library
