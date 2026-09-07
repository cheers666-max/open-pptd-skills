"""Small optional constructors for new PPTD decks; output stays ordinary PPTD YAML.

Import from the installed skill's scripts directory. Layout, content and sources
remain the author's decisions. Editing existing decks should preserve their paths.
"""
from pathlib import Path
import re
import yaml


class _Dumper(yaml.SafeDumper):
    pass


def _string(dumper, value):
    # PyYAML (YAML 1.1) leaves 08, 1e3 and 0o17 unquoted, while the JS
    # readers resolve them as numbers. Preserve labels across both parsers.
    style = '|' if '\n' in value or 'style=' in value else (
        "'" if re.match(r'^[+-]?(?:\d|\.\d)', value) else None)
    return dumper.represent_scalar('tag:yaml.org,2002:str', value,
        style=style)


_Dumper.add_representer(str, _string)


def text(identifier, x, y, width, height, value, **content):
    return dict(elementId=identifier, elementType='text', bounds=[x,y,width,height],
                content=dict(text=value, **content))


def shape(identifier, x, y, width, height, name='rect', **fields):
    return dict(elementId=identifier, elementType='shape', bounds=[x,y,width,height],
                shapeName=name, **fields)


def icon(identifier, x, y, width, height, name, **fields):
    return dict(elementId=identifier, elementType='icon', bounds=[x,y,width,height],
                iconName=name, **fields)


def line(identifier, x, y, width, height, points, **fields):
    return dict(elementId=identifier, elementType='line', bounds=[x,y,width,height],
                viewBox=fields.pop('viewBox', [width,height]), points=points, **fields)


def page(elements, *, page_type='content', background=None, notes=''):
    return dict(pageType=page_type, background=background or dict(type='solid',color='#FFFFFF'),
                notes=notes, elements=elements)


def write_project(directory, title, pages, *, theme=None, size=(960,540), overwrite=False):
    """Write a new deck and numbered pages. Existing target files require opt-in.

    Images/search slot comments are best added in .page files after serialization;
    no decorative fallback or factual source is inferred by these helpers.
    """
    directory = Path(directory)
    pages = list(pages)
    if not pages:
        raise ValueError('A deck needs at least one page')
    refs = [f'pages/{i:02d}.page' for i in range(1,len(pages)+1)]
    manifest = dict(version='v2', title=title, size=list(size), theme=theme or {}, pages=refs)
    documents = [(directory/'deck.pptd', manifest), *[(directory/ref, body) for ref,body in zip(refs,pages)]]
    # Serialize and check all destinations before writing any document.
    encoded = [(path, yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False)) for path,data in documents]
    if not overwrite and any(path.exists() for path,_ in encoded):
        raise FileExistsError('Target PPTD/page exists; use a new project or explicitly set overwrite=True')
    for path,data in encoded:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(data,encoding='utf-8')
    return directory/'deck.pptd'
