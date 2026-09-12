"""Image-source restrictions for the 360 intranet branch (stdlib only)."""
import json
from pathlib import Path
import urllib.parse
import urllib.request

# Off on this branch. The restriction belongs to the 360 intranet version, and the reason these
# sources reached decks here was a stale run snapshot whose BACKENDS still offered a wikimedia
# search — the current search offers none, so nothing is asking for them. Put a host back in this
# tuple to turn the guard on again; every consumer keeps working either way, since open_source
# stays the fetching path whether or not anything is listed.
BLOCKED_HOSTS = ()
MESSAGE = 'This image source is disabled for this deck; choose another source'


def blocked_source(url):
    if not isinstance(url, str):
        return False
    try:
        host = (urllib.parse.urlsplit(url).hostname or '').lower().rstrip('.')
    except ValueError:
        return False
    return any(host == domain or host.endswith('.' + domain) for domain in BLOCKED_HOSTS)


def blocked_record(record):
    if not isinstance(record, dict):
        return False
    return (str(record.get('backend', '')).lower() == 'wikimedia'
            or any(blocked_source(record.get(key)) for key in ('url', 'source_url', 'landing', 'foreign_landing_url'))
            or blocked_record(record.get('winner')))


def check_source(url):
    if blocked_source(url):
        raise ValueError(MESSAGE)


class SourceRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if blocked_source(newurl):
            fp.close()
            raise ValueError(MESSAGE)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_source(request, *, timeout):
    check_source(request.full_url if isinstance(request, urllib.request.Request) else request)
    return urllib.request.build_opener(SourceRedirectHandler()).open(request, timeout=timeout)


def check_local_provenance(project, references):
    """Reject a current local asset when its retained report identifies a blocked origin.

    Unattributed bytes cannot reveal their origin; the author must check supplied
    material provenance. Old/deleted slots do not block unrelated current assets.
    """
    project = Path(project)
    local = {(project / ref).resolve() for ref in references if isinstance(ref, str)
             and not ref.startswith(('http:', 'https:', 'data:', 'search:'))}
    try:
        report = json.loads((project / 'images_report.json').read_text())
    except (OSError, ValueError):
        return
    if not isinstance(report, dict) or not isinstance(report.get('slots'), list):
        return
    for record in report['slots']:
        if isinstance(record, dict) and isinstance(record.get('local'), str):
            if (project / record['local']).resolve() in local and blocked_record(record):
                raise ValueError(MESSAGE)
