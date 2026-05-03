#!/usr/bin/env python3
"""Run the WorldNet scheduler loop."""
import runpy
import sys

sys.path.insert(0, ".")

if __name__ == "__main__":
    runpy.run_module("app.tasks.scheduler", run_name="__main__")
