"""Bound all DOM data inside the browser before returning it to Python."""

SNAPSHOT = r"""({key, epoch, maxElements, maxText, maxLabel}) => {
 let store = window[key];
 if (!store) {
   store = window[key] = {epoch, next:0, entries:new Map(), identities:new WeakMap()};
   const invalidate = records => {
     const changed = records.some(r => !(r.type === 'attributes' &&
       r.attributeName === 'data-browser-agent-ref'));
     // Conservative: a modal/view change invalidates background elements too.
     if (changed) for (const item of store.entries.values()) item.version++;
   };
   store.observer = new MutationObserver(invalidate);
   store.flush = () => invalidate(store.observer.takeRecords());
   store.observer.observe(document,
     {subtree:true, childList:true, attributes:true, characterData:true});
 }
 store.flush();
 const trim = (s,n=maxLabel) => (s || '').replace(/\s+/g,' ').trim().slice(0,n);
 const visible = el => el.checkVisibility
   ? el.checkVisibility({checkOpacity:true, checkVisibilityCSS:true})
   : !!el.getClientRects().length && getComputedStyle(el).visibility === 'visible';
 const roleOf = el => {
   if (el.getAttribute('role')) return trim(el.getAttribute('role'));
   const tag = el.tagName.toLowerCase(), type = el.type;
   if (tag === 'a' && el.hasAttribute('href')) return 'link';
   if (tag === 'button' || (tag === 'input' &&
      ['button','submit','reset','image'].includes(type))) return 'button';
   if (tag === 'textarea' || el.isContentEditable) return 'textbox';
   if (tag === 'select') return el.multiple ? 'listbox' : 'combobox';
   if (tag === 'input') {
     if (['checkbox','radio'].includes(type)) return type;
     if (type === 'search') return 'searchbox';
     if (type === 'range') return 'slider';
     if (type === 'number') return 'spinbutton';
     return 'textbox';
   }
   return '';
 };
 // Never capture form values, password values, or editable text as page content.
 let text = '', scanned = 0;
 const walker = document.createTreeWalker(
   document.body || document.documentElement, NodeFilter.SHOW_TEXT);
 while (text.length < maxText && scanned++ < 50000 && walker.nextNode()) {
   const p = walker.currentNode.parentElement;
   if (p && !p.closest('script,style,noscript,input,textarea,[contenteditable]') && visible(p))
     text += trim(walker.currentNode.textContent, maxText-text.length) + ' ';
 }
 const elements = [], current = new Set();
 const selector = 'a[href],button,input:not([type=hidden]),textarea,select,' +
   '[role],[contenteditable=true],[tabindex]';
 for (const el of document.querySelectorAll(selector)) {
   if (elements.length >= maxElements) break;
   if (!visible(el)) continue;
   let token = store.identities.get(el);
   if (!token || !store.entries.has(token)) {
     token = store.epoch + '-' + (++store.next);
     store.identities.set(el,token);
     store.entries.set(token,{el,version:0});
     el.setAttribute('data-browser-agent-ref',token);
   }
   current.add(token);
   const item = store.entries.get(token);
   const labelledBy = (el.getAttribute('aria-labelledby') || '').split(/\s+/)
     .slice(0,10).map(id => document.getElementById(id)?.textContent || '').join(' ');
   const aria = trim(el.getAttribute('aria-label'));
   const editable = el.matches('input,textarea,[contenteditable]');
   const hasEditable = !!el.querySelector('textarea,[contenteditable]');
   elements.push({token,version:item.version,tag:el.tagName.toLowerCase(),
     type:trim(el.getAttribute('type')),role:roleOf(el),
     text:editable || hasEditable ? '' : trim(el.innerText),
     aria_label:aria || null,
     label:trim(aria || labelledBy || el.labels?.[0]?.innerText),
     placeholder:trim(el.getAttribute('placeholder')),name:trim(el.getAttribute('name')),
     checked:el.matches('input[type=checkbox],input[type=radio]')
       ? el.checked : el.getAttribute('aria-checked'),
     disabled:!!(el.disabled || el.getAttribute('aria-disabled')==='true')});
 }
 const headings=[];
 for (const h of document.querySelectorAll('h1,h2,h3,[role=heading]')) {
   if (headings.length >= 20) break;
   if (visible(h)) headings.push({text:trim(h.innerText)});
 }
 for (const [token,item] of store.entries)
   if (!item.el.isConnected || (maxElements > 0 && !current.has(token)))
     store.entries.delete(token);
 return {epoch:store.epoch,url:location.href.slice(0,2048),title:trim(document.title),
   headings,text:text.trim().slice(0,maxText),elements};
}"""

RESOLVE = r"""(el, {key,token,version,epoch}) => {
 const s=window[key]; if (!s || s.epoch!==epoch) return false;
 s.flush(); const item=s.entries.get(token);
 return !!(item && item.el===el && el.isConnected && item.version===version);
}"""
