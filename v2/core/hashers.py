"""Accept passwords imported from v1 (werkzeug format) so staff keep their passwords.

v1 hashes are re-packed into a compact form that fits Django's 128-character password column:
    wz$<s|p>:<params>$<salt>$<base64 digest>
On the first successful login Django re-hashes the password with its own algorithm.
"""
import base64
import hashlib

from django.contrib.auth.hashers import BasePasswordHasher
from django.utils.crypto import constant_time_compare


def from_werkzeug(werkzeug_hash):
    """'scrypt:32768:8:1$salt$hex' or 'pbkdf2:sha256:600000$salt$hex' -> compact Django form."""
    method, salt, hexdigest = werkzeug_hash.split("$", 2)
    parts = method.split(":")
    if parts[0] == "scrypt":
        params = "s:" + ":".join(parts[1:4] if len(parts) == 4 else ["32768", "8", "1"])
    elif parts[0] == "pbkdf2":
        params = "p:" + (parts[1] if len(parts) > 1 else "sha256") + ":" + (parts[2] if len(parts) > 2 else "600000")
    else:
        raise ValueError(f"unsupported v1 password hash: {parts[0]}")
    digest = base64.b64encode(bytes.fromhex(hexdigest)).decode()
    return f"wz${params}${salt}${digest}"


class WerkzeugImportedHasher(BasePasswordHasher):
    algorithm = "wz"

    def encode(self, password, salt):
        raise NotImplementedError("Only verifies passwords imported from v1.")

    def verify(self, password, encoded):
        try:
            _algo, params, salt, digest = encoded.split("$", 3)
            kind, *args = params.split(":")
            expected = base64.b64decode(digest)
        except ValueError:
            return False
        pw, salt_b = password.encode(), salt.encode()
        if kind == "s":
            n, r, p = (int(x) for x in args)
            got = hashlib.scrypt(pw, salt=salt_b, n=n, r=r, p=p, maxmem=132 * n * r * p, dklen=len(expected))
        elif kind == "p":
            got = hashlib.pbkdf2_hmac(args[0], pw, salt_b, int(args[1]))
        else:
            return False
        return constant_time_compare(got, expected)

    def safe_summary(self, encoded):
        return {"algorithm": self.algorithm}

    def must_update(self, encoded):
        return True

    def harden_runtime(self, password, encoded):
        pass
