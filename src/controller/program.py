from abc import abstractmethod


class Program:
    '''
    Abstract class for a program that can be run by the controller.
    '''

    def __init__(self, controller, session_id):
        self.controller = controller
        self.session_id = session_id
        self.state = 'READY'

    @abstractmethod
    def update_state(self):
        '''
        Toggle the state of the program from RUNNING to FINISHED.
        '''
        raise NotImplementedError

    @abstractmethod
    async def run(self, command):
        '''
        Run the program with the given command.
        '''
        raise NotImplementedError

    @abstractmethod
    def handle_done(self, ack_payload):
        '''
        Handle an DONE packet.
        '''
        raise NotImplementedError

    @abstractmethod
    def handle_reply(self, reply_payload, worker_id):
        '''
        Handle a REPLY packet. Returns True if the reply was handled.
        '''
        raise NotImplementedError
