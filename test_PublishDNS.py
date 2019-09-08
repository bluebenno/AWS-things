#!/usr/local/bin/python3

import unittest
from PublishDNS import run_os_command
from PublishDNS import poll_for_resolve
from PublishDNS import poll_for_cname_update


class SimpleTest(unittest.TestCase):

    def test_run_os_command(self):
        self.assertEqual(run_os_command("echo true"), "true\n")
        self.assertEqual(run_os_command("/sad-notthere-6d0b115"), -1)

    # Happy, lookup on www.google.com
    def test_poll_for_resolve(self):
        self.assertEqual(poll_for_resolve("www.google.com", 1), 0)
        self.assertEqual(poll_for_resolve("www.doesntexit.zoo", 1), -1)

    # Happy, lookup on www.microsoft.com
    # -> obviously if/when MS update their DNS...
    def test_poll_for_cname_update(self):
        self.assertEqual(poll_for_cname_update("www.microsoft.com", "www.microsoft.com-c-3.edgekey.net", 1), 0)
        self.assertEqual(poll_for_cname_update("www.microsoft.com", "notthis", 1), -1)

if __name__ == '__main__':
    unittest.main()
