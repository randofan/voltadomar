# Run
Create a tmux session for the controller, agent, and client. Run the following commands in the corresponding session.
1. run `python3 controller/controller.py --port 50051`
2. run `python3.11 agent/agent.py -a 1 -c localhost:50051` (this one needs python 3.11+)
2. run `python3 client/client.py 1 www.google.com`

# tmux
Currently all tmux sessions are running. To test, `tmux attach-session -t client` and run `python3 client.py`. Wait ~5 seconds and the output will appear in stdout. Note, there seems to be a bug causing the receive times for ICMP replies to be inflated by up to 50 milliseconds. This could be related to the datetime python library
