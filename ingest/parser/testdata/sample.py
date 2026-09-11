import os
from pathlib import Path

class Greeter:
    def hello(self, name):
        return greet(name)

def greet(name):
    return f"hi {name}"

def main():
    g = Greeter()
    print(g.hello("world"))
