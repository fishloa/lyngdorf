import sys
import logging

stdout_handler = logging.StreamHandler(stream=sys.stdout)


logging.basicConfig(level=logging.DEBUG, handlers=[stdout_handler])
