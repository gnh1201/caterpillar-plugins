#!/usr/bin/python3
#
# youareanidiot.py
# YouAreAnIdiot is the test filter for Caterpillar Proxy
#
# Namyheon Go (Catswords Research) <abuse@catswords.net>
# https://github.com/gnh1201/caterpillar
#
# Created in: 2022-10-25
# Updated in: 2022-10-25
#

from base import Extension, Logger

logger = Logger(name="youareanidiot", level=logging.WARNING)

class YouAreAnIdiot(Extension):
    def __init__(self):
        self.type = "filter"  # this is a filter
        
    def test(self, filtered, data, webserver, port, scheme, method, url):
        if data.find(b"youareanidiot") > -1:
            logger.warning("[*] Certainly, You are an idiot :)")
            return True

