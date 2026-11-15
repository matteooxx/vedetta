"""Platform adapters. One adapter serves every employer on that platform.

``ADAPTERS`` is the registry: platform name -> adapter class. A new adapter is
imported here and added below, and nowhere else.

It is one dictionary, and everything reaches that same object - ``run.ADAPTERS``,
``configstore.ADAPTERS``, the interface through ``run``. The tests replace entries in
it with ``monkeypatch.setitem(run.ADAPTERS, ...)``; a copy anywhere would let those
tests pass while patching a dictionary the code never reads. Import the name, never
rebuild or copy the dictionary.
"""
from .greenhouse import GreenhouseAdapter
from .sitemap import SitemapAdapter
from .smartrecruiters import SmartRecruitersAdapter
from .workday import WorkdayAdapter

ADAPTERS = {
    GreenhouseAdapter.platform: GreenhouseAdapter,
    SitemapAdapter.platform: SitemapAdapter,
    SmartRecruitersAdapter.platform: SmartRecruitersAdapter,
    WorkdayAdapter.platform: WorkdayAdapter,
}
