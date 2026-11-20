# The one place the add-on opens a URL. urllib's urlopen also accepts file:// and other schemes;
# every request here goes to the EasyPDM server address the user typed in, so anything that is
# not http or https is refused before it is opened (Bandit B310, as the Addon Index scans).

from urllib import request
from urllib.parse import urlsplit


def urlopen(req, timeout):
    """urllib.request.urlopen for http(s) only; `req` is a Request or a URL string."""
    url = req.full_url if isinstance(req, request.Request) else str(req)
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError("EasyPDM: refusing to open a %s:// address: %s" % (scheme or "relative", url))
    # Audited: only http and https reach this point, checked just above (added nosec B310)
    return request.urlopen(req, timeout=timeout)  # nosec B310
