import subprocess

class Subprocess(object):
    def __init__(self, command):
        self.subprocess = subprocess.Popen(
            command, 
            shell=False, 
            stdout=subprocess.PIPE, 
            stdin=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )  

    def read(self):
        result = self.subprocess.stdout.readline()
        self.subprocess.stout.flush()
        result = result.decode("utf-8")
        return result

    def write(self, data):
        self.subprocess.stdin.write(data.encode("utf-8"))
        self.subprocess.stdin.flush()