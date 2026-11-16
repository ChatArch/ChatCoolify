"""Progressively enhanced, authorization-preserving website catalog presentation."""
from __future__ import annotations

import hashlib
import html
from urllib.parse import urlsplit


def render_card(project, addresses, management):
    """Render only the project's already-authorized data, never probe its sites."""
    escape = lambda value: html.escape(str(value or ''), quote=True)
    environments = {row['environment']: row for row in addresses['environments']}
    production = environments.get('production', {}).get('current_url')
    preview = environments.get('preview', {}).get('current_url')
    state = 'published' if production else ('preview' if preview else 'draft')
    state_label = {'published': '已发布', 'preview': '仅预览', 'draft': '尚未发布'}[state]
    role = {'owner': '所有者', 'deployer': '可部署', 'viewer': '可阅读'}.get(project['role'], project['role'])
    visibility = '公开' if project['visibility'] == 'public' else '仅登录'
    name, slug = project['name'], project['slug']
    project_id = escape(project['id'])
    search = ' '.join([name, slug] + [str(row.get(key) or '')
        for row in addresses['environments'] for key in ('current_url', 'desired_url')])
    color = int(hashlib.sha256(project['id'].encode()).hexdigest()[:2], 16) % 4
    icon = escape(name.strip()[:1] or slug[:1]).upper()
    current = production or preview
    address = escape(urlsplit(current).netloc) if current else '发布后显示访问地址'
    actions = []
    if production:
        actions.append(f'<a class="site-open" href="{escape(production)}" target="_blank" rel="noopener noreferrer">打开网站 <span aria-hidden="true">↗</span></a>')
    if preview:
        actions.append(f'<a class="site-preview" href="{escape(preview)}" target="_blank" rel="noopener noreferrer">打开预览 <span aria-hidden="true">↗</span></a>')
    if not current:
        actions.append('<span class="site-unpublished">尚无可访问入口</span>')
    actions.append(f'<a class="site-manage" data-manage="project-{project_id}" href="#project-{project_id}">管理</a>')
    return (f'<article class="site-card" id="project-{project_id}" data-name="{escape(name)}" '
        f'data-search="{escape(search)}" data-state="{state}" data-visibility="{escape(project["visibility"])}">'
        f'<div class="site-top"><div class="site-icon tone-{color}" aria-hidden="true">{icon}</div>'
        f'<div class="site-heading"><div class="site-meta"><span class="site-state state-{state}">{state_label}</span>'
        f'<span class="site-visibility">{visibility}</span></div><h2>{escape(name)}</h2>'
        f'<p class="site-slug">{escape(slug)}</p></div></div>'
        f'<p class="site-address">{address}</p><div class="site-actions">{"".join(actions)}</div>'
        f'<details class="management"><summary>项目管理 <span>{escape(role)}</span></summary>'
        f'<div class="management-body">{management}</div></details></article>')


TOOLBAR = '''<section class="catalog-toolbar" id="catalog-toolbar" aria-label="网站目录工具" hidden>
<label class="catalog-search">搜索网站<input id="catalog-search" type="search" placeholder="搜索名称、标识或域名" autocomplete="off"></label>
<label>访问方式<select id="catalog-visibility" aria-label="访问方式"><option value="all">全部访问方式</option><option value="public">公开网站</option><option value="private">仅登录网站</option></select></label>
<label>发布状态<select id="catalog-state" aria-label="发布状态"><option value="all">全部发布状态</option><option value="published">已发布</option><option value="preview">仅预览</option><option value="draft">尚未发布</option></select></label>
<div class="view-switch" role="group" aria-label="目录视图"><button type="button" data-view-choice="cards" aria-pressed="true"><span aria-hidden="true">▦</span> 卡片</button><button type="button" data-view-choice="list" aria-pressed="false"><span aria-hidden="true">☷</span> 列表</button></div>
</section>'''

STYLE = '''
header,main{max-width:1280px}header{padding-top:22px;padding-bottom:22px}header>a{font-size:20px;letter-spacing:-.5px}.account .create-link{font-weight:500;color:#3c5e43}.catalog-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:26px 0 22px}.catalog-heading h1{margin:0 0 6px;letter-spacing:-1px}.catalog-heading .intro{margin:0;max-width:650px}.catalog-eyebrow{font-size:12px;font-weight:700;letter-spacing:2px;color:#73816e;margin:0 0 8px}.catalog-total{flex-shrink:0;font-size:14px;color:#687563;padding-bottom:3px}.catalog-toolbar{display:flex;align-items:end;gap:12px;background:#fff;border:1px solid #dce2d8;border-radius:12px;padding:16px;margin-bottom:18px}.catalog-toolbar[hidden]{display:none}.catalog-toolbar label{font-size:12px;gap:6px}.catalog-search{flex:1;min-width:180px}.catalog-toolbar input,.catalog-toolbar select{width:100%;font-size:14px;height:42px}.view-switch{display:flex;gap:3px;background:#f1f4ee;padding:3px;border:1px solid #e1e7db;border-radius:8px;flex-shrink:0}.view-switch button{border:0;background:transparent;padding:7px 11px;font-size:13px;line-height:22px}.view-switch button[aria-pressed="true"]{background:#fff;color:#244c32;box-shadow:0 1px 4px #253d221a}.catalog-result{font-size:13px;color:#687563;margin:0 0 14px}.catalog-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;align-items:start}.catalog-grid [hidden],.catalog-no-results[hidden]{display:none!important}.catalog-grid .site-card{padding:22px 22px 0;border-radius:14px;display:flex;flex-direction:column;box-shadow:0 2px 4px #172e1910;transition:border-color .15s,box-shadow .15s}.site-card:hover{border-color:#b8c9b0;box-shadow:0 6px 20px #172e1910}.site-card:target{outline:2px solid #78966c;outline-offset:3px}.site-top{display:flex;gap:14px;align-items:center;min-width:0}.site-icon{width:56px;height:56px;border-radius:14px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:25px;font-weight:600;border:1px solid #31492f0a}.tone-0{background:#e8efdf;color:#476141}.tone-1{background:#e5edef;color:#436374}.tone-2{background:#f2ecde;color:#826b3c}.tone-3{background:#ece8f0;color:#6b547c}.site-heading{min-width:0;flex:1}.site-heading h2{font-size:19px;line-height:1.5;margin:4px 0 0;letter-spacing:-.3px}.site-meta{display:flex;align-items:center;flex-wrap:wrap;gap:9px;font-size:11px;line-height:1.7}.site-state{display:inline-flex;align-items:center;gap:5px;font-weight:500}.site-state:before{content:"";width:5px;height:5px;border-radius:50%;background:currentColor}.state-published{color:#4b7045}.state-preview{color:#8b6b2e}.state-draft{color:#7c8378}.site-visibility{color:#7e8779;border-left:1px solid #dce2d8;padding-left:9px}.site-slug{font-size:12px;color:#7c8776;margin:0;overflow-wrap:anywhere}.site-address{margin:22px 0 18px;font-size:13px;color:#6a7765;overflow-wrap:anywhere;min-height:21px}.site-actions{display:flex;align-items:center;flex-wrap:wrap;gap:14px;min-height:36px;margin:0 0 18px}.site-actions a{font-size:13px;text-decoration:none;font-weight:500}.site-open{color:#2d5235;background:#edf3e8;padding:7px 12px;border-radius:7px}.site-preview{color:#61725b}.site-manage{margin-left:auto;color:#64745e}.site-actions a:hover{text-decoration:underline}.site-unpublished{font-size:13px;color:#8a9185}.site-card .management{margin:0 -22px;padding:0;border-top:1px solid #e6ebe2;border-radius:0 0 14px 14px}.management>summary{padding:12px 22px;font-size:12px;color:#6c7a66}.management>summary span{float:right;font-size:11px;color:#84907d}.management-body{padding:0 22px 22px}.management .address{margin:20px 0}.management .address strong{font-size:13px}.management .visibility-form{margin-top:8px}.site-card:has(.management[open]){grid-column:1/-1}.catalog-grid[data-view="list"]{grid-template-columns:1fr;gap:10px}.catalog-grid[data-view="list"] .site-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:0 26px;padding-top:18px}.catalog-grid[data-view="list"] .site-top{grid-row:1/3;align-self:center}.catalog-grid[data-view="list"] .site-icon{width:46px;height:46px;border-radius:11px;font-size:22px}.catalog-grid[data-view="list"] .site-heading h2{font-size:17px}.catalog-grid[data-view="list"] .site-address{grid-column:2;grid-row:1;margin:0 0 7px;text-align:right;max-width:380px}.catalog-grid[data-view="list"] .site-actions{grid-column:2;grid-row:2;justify-content:flex-end;margin:0 0 14px}.catalog-grid[data-view="list"] .management{grid-column:1/-1}.catalog-grid[data-view="list"] .site-manage{margin-left:0}.catalog-no-results,.catalog-empty{padding:48px 24px;text-align:center;border:1px dashed #cbd6c3;border-radius:14px;background:#f9fbf6;margin:0}.catalog-no-results h2,.catalog-empty h2{font-size:18px}.catalog-no-results p,.catalog-empty p{color:#76826e;font-size:14px}.catalog-empty a{color:#385a35}.create{margin-top:30px}main>aside{font-size:12px;color:#6b7864;background:transparent;padding:0;margin-bottom:26px}.site-actions a:focus-visible,summary:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #66835c;outline-offset:3px}
@media(max-width:1050px){.catalog-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.catalog-toolbar{flex-wrap:wrap}.catalog-search{min-width:260px}.catalog-toolbar .view-switch{margin-left:auto}}
@media(max-width:680px){header,main{padding:18px}.account{gap:10px}.account .create-link{display:none}.catalog-heading{display:block;margin-top:16px}.catalog-heading h1{font-size:28px}.catalog-total{display:block;margin-top:10px}.catalog-heading .intro{font-size:14px}.catalog-toolbar{gap:10px;padding:12px}.catalog-search{flex-basis:100%;min-width:0}.catalog-toolbar label:not(.catalog-search){flex:1;min-width:0}.catalog-toolbar select{padding-left:7px;font-size:13px}.catalog-toolbar .view-switch{margin-left:0;width:100%}.view-switch button{flex:1}.catalog-grid{grid-template-columns:1fr;gap:14px}.catalog-grid .site-card{padding:20px 20px 0}.site-card .management{margin:0 -20px}.management>summary{padding-left:20px;padding-right:20px}.management-body{padding-left:20px;padding-right:20px}.catalog-grid[data-view="list"] .site-card{display:flex}.catalog-grid[data-view="list"] .site-address{text-align:left;margin:14px 0 10px;max-width:none}.catalog-grid[data-view="list"] .site-actions{justify-content:flex-start;margin-bottom:14px}.catalog-grid[data-view="list"] .site-manage{margin-left:auto}.management .address{grid-template-columns:1fr;gap:6px}.management form label,.management form input,.management form select{width:100%}.management .suffix{flex-basis:100%}.management form button{width:100%}}
'''

SCRIPT = r'''
(()=>{
 const catalog=document.getElementById('site-catalog');
 if(!catalog)return;
 const cards=Array.from(catalog.querySelectorAll('.site-card'));
 const search=document.getElementById('catalog-search'),visibility=document.getElementById('catalog-visibility'),state=document.getElementById('catalog-state');
 const count=document.getElementById('catalog-count'),empty=document.getElementById('catalog-no-results');
 const choices=Array.from(document.querySelectorAll('[data-view-choice]'));
 const storageKey='chatcoolify.catalog.view';
 function setView(value){const view=value==='list'?'list':'cards';catalog.dataset.view=view;choices.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.viewChoice===view)));try{localStorage.setItem(storageKey,view)}catch(e){}}
 function filter(){const query=search.value.trim().toLocaleLowerCase();let shown=0;cards.forEach(card=>{const match=(!query||card.dataset.search.toLocaleLowerCase().includes(query))&&(visibility.value==='all'||card.dataset.visibility===visibility.value)&&(state.value==='all'||card.dataset.state===state.value);card.hidden=!match;if(match)shown++});count.textContent='显示 '+shown+' / '+cards.length+' 个网站';empty.hidden=shown>0||cards.length===0;}
 function reveal(id){const card=cards.find(item=>item.id===id);if(!card)return;search.value='';visibility.value='all';state.value='all';filter();const panel=card.querySelector('.management');if(panel)panel.open=true;requestAnimationFrame(()=>card.scrollIntoView({block:'start'}));}
 search.addEventListener('input',filter);visibility.addEventListener('change',filter);state.addEventListener('change',filter);
 choices.forEach(button=>button.addEventListener('click',()=>setView(button.dataset.viewChoice)));
 document.getElementById('catalog-reset').addEventListener('click',()=>{search.value='';visibility.value='all';state.value='all';filter();search.focus()});
 document.querySelectorAll('[data-manage]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();if(location.hash!=='#'+link.dataset.manage)location.hash=link.dataset.manage;reveal(link.dataset.manage)}));
 window.addEventListener('hashchange',()=>reveal(location.hash.slice(1)));
 try{setView(localStorage.getItem(storageKey))}catch(e){setView('cards')}
 document.getElementById('catalog-toolbar').hidden=false;filter();reveal(location.hash.slice(1));
})();
'''
