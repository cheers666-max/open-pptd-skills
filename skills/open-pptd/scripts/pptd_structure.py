"""Small, shared guards for authored page structures; not a full PPTD schema.

Keep bad container/scalar types out of renderers and heuristic layout checks.
Report errors without flattening, coercing or otherwise rewriting author data.
"""
import math

ELEMENT_TYPES = {'text', 'shape', 'line', 'image', 'icon', 'table', 'chart'}


def finite_number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def page_structure_issues(page, page_number=1, page_ref=''):
    issues = []

    def error(location, message, element_id=None, code='invalid-field'):
        issues.append(dict(code=code, pageNumber=page_number, pageRef=page_ref,
                           elementId=element_id, location=location, message=message,
                           repairability='format'))

    if not isinstance(page, dict):
        error('/', 'Page must be an object containing an elements list.', code='invalid-page')
        return issues
    elements = page.get('elements')
    if not isinstance(elements, list):
        error('/elements', 'elements must be a list of element objects.', code='invalid-page')
        return issues
    if page.get('background') is not None and not isinstance(page['background'], dict):
        error('/background', 'background must be a Fill object.')
    seen_ids = set()
    for index, element in enumerate(elements):
        base = f'/elements/{index}'
        if not isinstance(element, dict):
            error(base, 'Element must be an object; nested lists and scalar values are invalid.',
                  code='invalid-element')
            continue
        identifier = element.get('elementId')
        if not isinstance(identifier, str) or not identifier.strip():
            error(base + '/elementId', 'elementId must be a non-empty string.')
        elif identifier in seen_ids:
            error(base + '/elementId', 'elementId must be unique within the page.', identifier,
                  code='duplicate-element-id')
        else:
            seen_ids.add(identifier)
        kind = element.get('elementType')
        if not isinstance(kind, str) or kind not in ELEMENT_TYPES:
            error(base + '/elementType', 'Unsupported elementType; use text/shape/line/image/icon/table/chart.', identifier)
        bounds = element.get('bounds')
        if (not isinstance(bounds, list) or len(bounds) != 4 or
                not all(finite_number(v) for v in bounds) or bounds[2] < 0 or bounds[3] < 0):
            error(base + '/bounds', 'bounds must contain four finite numbers [x,y,width,height], with nonnegative dimensions.', identifier)
        if 'opacity' in element and (not finite_number(element['opacity']) or not 0 <= element['opacity'] <= 1):
            error(base + '/opacity', 'opacity must be a finite number in [0,1].', identifier)
        for key in ('fill', 'border', 'shadow'):
            if element.get(key) is not None and not isinstance(element[key], dict):
                error(base + '/' + key, f'{key} must be an object.', identifier)
        if kind == 'text':
            content = element.get('content')
            if not isinstance(content, dict):
                error(base + '/content', 'Text content must be an object.', identifier)
            else:
                value = content.get('text')
                # Existing HTML/PPTX readers also stringify boolean/numeric labels.
                if not isinstance(value, (str, bool)) and not finite_number(value):
                    error(base + '/content/text', 'text must be a string, boolean or finite numeric label.', identifier)
        if kind == 'image' and (not isinstance(element.get('src'), str) or not element['src'].strip()):
            error(base + '/src', 'Image src must be a non-empty string.', identifier)
    return issues
