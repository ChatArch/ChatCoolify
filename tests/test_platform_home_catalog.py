"""Catalog contracts use isolated local fixtures, never production accounts."""
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from chatcoolify.platform_web import COOKIE, PlatformHandler
from test_platform_domains import setup
from test_platform_management import local_server, upload


class CatalogDOM(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def by_id(self, value):
        return next(attrs for _, attrs in self.elements if attrs.get('id') == value)


def page_for(service, actor):
    username = service.live(actor).username
    login = service.login(username, 'Example-' + username + '-password!')
    with local_server(PlatformHandler, platform=service) as origin:
        with urlopen(Request(origin + '/', headers={'Cookie': COOKIE + '=' + login['token']})) as response:
            return response.read().decode()


def test_home_catalog_controls_and_authorized_project_states(setup, tmp_path):
    service, native, owner, other = setup
    published = service.create_project(owner, 'published-site', name='同名网站', request_key='published')
    preview = service.create_project(owner, 'preview-site', name='同名网站', visibility='private', request_key='preview')
    draft = service.create_project(owner, 'draft-site', request_key='draft')
    hidden = service.create_project(other, 'not-my-project', request_key='hidden')
    release = upload(service, native, owner, published, tmp_path, 'published')
    service.deploy(owner, published['id'], release['id'], environment='production', request_key='publish')
    release = upload(service, native, owner, preview, tmp_path, 'preview')
    service.deploy(owner, preview['id'], release['id'], environment='preview', request_key='preview')
    service.set_domain(owner, published['id'], 'pending-name')
    page = page_for(service, owner)
    dom = CatalogDOM()
    dom.feed(page)
    assert dom.by_id('site-catalog')['data-view'] == 'cards'
    assert dom.by_id('catalog-search')['type'] == 'search'
    assert dom.by_id('catalog-visibility')['aria-label'] == '访问方式'
    assert dom.by_id('catalog-state')['aria-label'] == '发布状态'
    assert dom.by_id('catalog-count')['aria-live'] == 'polite'
    assert dom.by_id('catalog-no-results')['hidden'] is None
    assert {attrs['data-view-choice'] for _, attrs in dom.elements if 'data-view-choice' in attrs} == {'cards', 'list'}
    assert dom.by_id('project-' + published['id'])['data-state'] == 'published'
    assert dom.by_id('project-' + preview['id'])['data-state'] == 'preview'
    assert dom.by_id('project-' + draft['id'])['data-state'] == 'draft'
    assert dom.by_id('project-' + preview['id'])['data-visibility'] == 'private'
    assert 'pending-name.example.test' in dom.by_id('project-' + published['id'])['data-search']
    assert hidden['id'] not in page and 'not-my-project' not in page
    links = [attrs.get('href') for tag, attrs in dom.elements if tag == 'a']
    assert 'https://published-site.example.test' in links
    assert 'https://preview-site-preview.example.test' in links
    assert 'https://pending-name.example.test' not in links
    assert not any('draft-site.example.test' in (link or '') for link in links)
    assert len([attrs for tag, attrs in dom.elements if tag == 'article' and 'site-card' in attrs.get('class', '')]) == 3
    assert '仅预览' in page and '尚未发布' in page and '已发布' in page
    assert '在线' not in page
    assert 'hashchange' in page and 'data-manage' in page


def test_catalog_shared_viewer_keeps_links_without_owner_forms(setup):
    service, native, owner, viewer = setup
    project = service.create_project(owner, 'shared-catalog', request_key='shared')
    service.grant(owner, project['id'], viewer.user_id, 'viewer')
    page = page_for(service, viewer)
    dom = CatalogDOM()
    dom.feed(page)
    assert dom.by_id('project-' + project['id'])['data-state'] == 'draft'
    assert '可阅读' in page
    assert not [attrs for tag, attrs in dom.elements if tag == 'form' and attrs.get('data-project') == project['id']]
    assert '项目管理' in page


def test_catalog_empty_state_and_hostile_project_title_are_escaped(setup):
    service, native, owner, other = setup
    empty = page_for(service, owner)
    assert 'id="site-catalog"' in empty and '还没有网站' in empty
    project = service.create_project(owner, 'escaped-name', name='<img src=x onerror=alert(1)>', request_key='escaped')
    page = page_for(service, owner)
    assert '<img src=x' not in page
    assert '&lt;img src=x onerror=alert(1)&gt;' in page
    dom = CatalogDOM()
    dom.feed(page)
    assert dom.by_id('project-' + project['id'])['data-name'] == project['name']
