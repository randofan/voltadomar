import argparse


def parse_traceroute_args(command):
    '''
    Parse the arguments for the traceroute program.
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=str)
    parser.add_argument('destination', type=str)
    parser.add_argument('-m', '--max-hops', type=int, default=20)
    parser.add_argument('-t', '--timeout', type=int, default=10)
    parser.add_argument('-n', '--probe-num', type=int, default=3)

    # Usage: volta <source> <destination> [-m <max hops>] [-t <timeout>] [-n <probe num>]
    args = parser.parse_args(command.split()[1:])  # exclude 'volta' prefix
    return (args.source, args.destination, args.max_hops,
            args.timeout, args.probe_num)
