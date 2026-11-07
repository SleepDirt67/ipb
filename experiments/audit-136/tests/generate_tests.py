"""Extract actual changed function bodies; keep assertions active in Release."""
from pathlib import Path
import subprocess,sys
engine=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=True)
# Baseline source snapshots are written by the overlay BEFORE it applies changes.
base=Path(sys.argv[3]).resolve()
def read(path,old=False):return ((base if old else engine)/path).read_bytes().decode('latin1').replace('\r\n','\n')
def body(s,signature):
 start=s.index(signature);a=s.index('{',start);depth=1;i=a+1
 while depth:
  if s[i]=='{':depth+=1
  elif s[i]=='}':depth-=1
  i+=1
 return s[start:i]
common='''#undef NDEBUG
#include <cassert>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#include <unordered_map>
#include <algorithm>
#include <iterator>
#include <random>
#include <chrono>
#include <cstdio>
'''
s=common+r'''using Root=std::vector<struct Sect*>;
struct Str {std::string s;const char*operator*()const{return s.c_str();}};
struct Sect {Str Name;unsigned value;};
#define xr_strcmp std::strcmp
bool sect_pred(const Sect*x,const char*v){return x->Name.s<v;}
using RootIt=Root::iterator;
'''
for old,name in [(True,'old_load'),(False,'new_load')]:
 text=read('src/xrCore/Xr_ini.cpp',old);a=text.index('\t// Insert all finalized sections' if old else '    // Build the sorted suffix');b=text.index('\n\t// Clean modifiers',a)
 s+='void '+name+'(Root& DATA,std::unordered_map<std::string,Sect>& FinalData){\n'+text[a:b]+'\n}\n'
s+=r'''std::vector<std::pair<std::string,unsigned>> snapshot(const Root&r){std::vector<std::pair<std::string,unsigned>>s;for(auto*p:r)s.push_back({p->Name.s,p->value});return s;}
void cleanup(Root&r){for(auto*p:r)delete p;r.clear();}
int main(){std::mt19937 rng(771);unsigned cases=0;
 for(int t=0;t<5000;++t){Root a,b;std::unordered_map<std::string,Sect> input;
  for(unsigned i=0;i<rng()%80;++i){std::string n="s"+std::to_string(rng()%100);a.push_back(new Sect{{n},i});b.push_back(new Sect{{n},i});}
  auto less=[](const Sect*a,const Sect*b){return a->Name.s<b->Name.s;};std::stable_sort(a.begin(),a.end(),less);std::stable_sort(b.begin(),b.end(),less);
  for(unsigned i=0;i<rng()%100;++i){std::string n="s"+std::to_string(rng()%100);input[n]={{n},1000+i};}
  old_load(a,input);new_load(b,input);assert(snapshot(a)==snapshot(b));cleanup(a);cleanup(b);++cases;
 }
 printf("Materialization: %u differential cases including existing DATA/equal names/empty\n",cases);
 for(int n:{1,16,256,4096,16000}){std::unordered_map<std::string,Sect> input;for(int i=0;i<n;++i){std::string key="s"+std::to_string(i);input[key]={{key},unsigned(i)};}Root a,b;
 auto start=std::chrono::steady_clock::now();old_load(a,input);auto mid=std::chrono::steady_clock::now();new_load(b,input);auto end=std::chrono::steady_clock::now();assert(snapshot(a)==snapshot(b));
 printf("materialize synthetic sections=%d old_ms=%.6f new_ms=%.6f\n",n,std::chrono::duration<double,std::milli>(mid-start).count(),std::chrono::duration<double,std::milli>(end-mid).count());cleanup(a);cleanup(b);}
}
'''
(out/'materialization.cpp').write_text(s,encoding="utf-8")
# Compile the repository's actual TinyXML implementation, with only its PCH removed.
xml='src/xrCore/FormatParsers/XML/'
(out/'tinyxml.h').write_bytes((engine/xml/'tinyxml.h').read_bytes())
(out/'tinyxml.cpp').write_text(read(xml+'tinyxml.cpp').replace('#include "stdafx.h"','// Test-only adaptation: engine PCH removed.'),encoding='latin1')
s=common+r'''#include "tinyxml.h"
using XML_NODE=tinyxml2::XMLNode;using LPCSTR=const char*;using string_path=char[1024];
#define R_ASSERT3(x,...) assert(x)
#define R_ASSERT(x) assert(x)
#define VERIFY(x) assert(x)
#define xr_strlen std::strlen
#define xr_strcpy(dst,src) std::strcpy(dst,src)
'''
for old,name in [(True,'old_xml'),(False,'new_xml')]:
 f=body(read(xml+'xrXMLParser.cpp',old),'XML_NODE* CXml::NavigateToNode(XML_NODE* start_node, LPCSTR  path, int node_index)')
 s+=f.replace('CXml::NavigateToNode',name)+'\n'
s+=r'''int main(){tinyxml2::XMLDocument doc;assert(doc.Parse("<root><a id='0'><b><c/></b></a><a id='1'/><x/><cell_item_text/><condition_progess_bar/></root>")==tinyxml2::XML_SUCCESS);auto*r=doc.FirstChildElement("root");
 unsigned n=0;std::vector<std::string>paths={"","a","a:b","a:b:c",":a", "a:","::a:::b::",":","missing","a:missing:x","cell_item_text","condition_progess_bar","a:b:c:d"," x"};
 for(const auto&p:paths)for(int index=-2;index<8;++index){assert(old_xml(r,p.c_str(),index)==new_xml(r,p.c_str(),index));++n;}
 std::mt19937 rng(73);for(int i=0;i<10000;++i){std::string path;for(unsigned j=0;j<rng()%10;++j)path+=std::vector<std::string>{"a","b","c",":","::","missing"}[rng()%6];int index=int(rng()%9)-2;assert(old_xml(r,path.c_str(),index)==new_xml(r,path.c_str(),index));++n;}
 // No persistent lookup cache: node insertion/removal and another root are seen.
 auto*added=doc.NewElement("later");r->InsertEndChild(added);assert(new_xml(r,"later",0)==added);r->DeleteChild(added);assert(!new_xml(r,"later",0));
 printf("XML: %u differential paths/index cases; real TinyXML and mutation checks\n",n);
 volatile XML_NODE* sink=nullptr;for(auto fn:{old_xml,new_xml}){auto start=std::chrono::steady_clock::now();for(int i=0;i<500000;++i)sink=fn(r,"cell_item_text",0);printf("xml synthetic calls=500000 ms=%.6f\n",std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());}assert(sink);}
'''
(out/'xml_navigation.cpp').write_text(s,encoding="utf-8")
# Exact PopChild bodies; mocks record ownership, pointer swaps and redraw work.
s=common+r'''using u32=unsigned;
#define R_ASSERT(x) assert(x)
struct CUICellItem {std::vector<CUICellItem*>m_childs;void*m_pData=nullptr;bool owner=true;unsigned updates=0;
 unsigned ChildsCount(){return unsigned(m_childs.size());}void SetOwnerList(void*){owner=false;}void UpdateItemText(){++updates;}
 CUICellItem*PopChild(CUICellItem*);CUICellItem*PopChildForDestroy();};
'''
s+=body(read('src/xrGame/ui/UICellItem.cpp',True),'CUICellItem* CUICellItem::PopChild(CUICellItem* needed)')+'\n'+body(read('src/xrGame/ui/UICellItem.cpp'),'CUICellItem* CUICellItem::PopChildForDestroy()')+'\n'
s+=r'''int main(){unsigned cases=0;for(unsigned n=0;n<=1000;++n){CUICellItem a,b;a.m_pData=b.m_pData=reinterpret_cast<void*>(1);std::vector<CUICellItem>va(n),vb(n);for(unsigned i=0;i<n;++i){va[i].m_pData=vb[i].m_pData=reinterpret_cast<void*>(size_t(i)+2);a.m_childs.push_back(&va[i]);b.m_childs.push_back(&vb[i]);}
 while(a.ChildsCount()){auto*x=a.PopChild(nullptr);auto*y=b.PopChildForDestroy();assert(x->m_pData==y->m_pData);assert(x->owner==y->owner);assert(a.m_pData==b.m_pData);assert(a.ChildsCount()==b.ChildsCount());++cases;}assert(b.updates==0);assert(a.updates==n);}
 printf("Cell destruction: %u exact-body pointer/ownership/order checks; zero dead-stack redraws\n",cases);
 // Vector erase traversal: odd/even roots, ignored roots, same reverse order.
 for(unsigned n=0;n<100;++n)for(unsigned mask=0;mask<16;++mask){std::vector<unsigned>v,removed;for(unsigned i=0;i<n;++i)v.push_back(i);size_t remaining=v.size();while(remaining){auto x=v[--remaining];if(mask&(1u<<(x%4)))continue;removed.push_back(x);v.erase(v.begin()+remaining);}std::vector<unsigned>expected;for(unsigned i=0;i<n;++i)if(mask&(1u<<(i%4)))expected.push_back(i);assert(v==expected);assert(std::is_sorted(removed.rbegin(),removed.rend()));} }
'''
(out/'cell_cleanup.cpp').write_text(s,encoding="utf-8")
print('Generated materialization, real TinyXML, exact cell cleanup tests')
# Full register/find/discard/destroy bodies, including first duplicate replacement.
s=common+r'''
using BOOL=bool;constexpr bool TRUE=true,FALSE=false;
#define VERIFY(x) assert(x)
#define xr_strcmp std::strcmp
template<class T>using xr_vector=std::vector<T>;
struct Str {std::string s;Str()=default;Str(const char*p):s(p?p:""){};Str&operator=(const char*p){s=p?p:"";return*this;}const char*operator*()const{return s.c_str();}char operator[](size_t i)const{return s[i];}size_t size()const{return s.size();}bool operator==(const Str&)const=default;};
using shared_str=Str;
struct dxRender_Visual{unsigned id;void Release(){};};
template<class T>void xr_delete(T*&p){delete p;p=nullptr;}
struct Motions{void clean(bool){}} motions;auto*g_pMotionsContainer=&motions;
struct CommonPool {
 struct ModelDef {Str name;dxRender_Visual*model=nullptr;unsigned refs=0;};
 std::vector<ModelDef>Models;std::map<std::string,dxRender_Visual*,std::less<>>ModelsByName;
 using REGISTRY_IT=std::map<dxRender_Visual*,Str>::iterator;std::map<dxRender_Visual*,Str>Registry;std::map<std::string,dxRender_Visual*>Pool;bool bForceDiscard=false;
};
'''
for old,name in [(True,'OldPool'),(False,'NewPool')]:
 s+='struct '+name+':CommonPool {void Instance_Register(const char*,dxRender_Visual*);dxRender_Visual*Instance_Find(const char*);void Discard(dxRender_Visual*&,BOOL);void Destroy();void DeleteInternal(dxRender_Visual*&v,BOOL b){Discard(v,b);}};\n'
 source=subprocess.check_output(['git','-C',str(engine),'show','612b165c97d5e6a50ac0a6d1384ac8c95a63dda5:src/Layers/xrRender/ModelPool.cpp']).decode('latin1').replace('\r\n','\n') if old else read('src/Layers/xrRender/ModelPool.cpp')
 for signature in ['void CModelPool::Instance_Register(', 'dxRender_Visual* CModelPool::Instance_Find(', 'void CModelPool::Discard(', 'void CModelPool::Destroy(']:
  s+=body(source,signature).replace('CModelPool::',name+'::')+'\n'
s+=r'''
int main(){OldPool a;NewPool b;std::mt19937 rng(448);unsigned serial=1,checks=0;
 for(unsigned i=0;i<10000;++i){
  if(a.Models.empty()||rng()%3){std::string name=std::vector<std::string>{"a","A","dup","dup#","", "models\\npc"}[rng()%6];a.Instance_Register(name.c_str(),new dxRender_Visual{serial});b.Instance_Register(name.c_str(),new dxRender_Visual{serial++});a.Models.back().refs=b.Models.back().refs=1;}
  else {std::string name=a.Models[rng()%a.Models.size()].name.s;auto*x=new dxRender_Visual{serial};auto*y=new dxRender_Visual{serial++};a.Registry[x]=name.c_str();b.Registry[y]=name.c_str();a.Discard(x,TRUE);b.Discard(y,TRUE);assert(!x&&!y);}
  for(const auto*key:{"a","A","dup","dup#","","models\\npc","absent"}){auto*x=a.Instance_Find(key);auto*y=b.Instance_Find(key);assert(bool(x)==bool(y));if(x)assert(x->id==y->id);++checks;}
  assert(a.Models.size()==b.Models.size());
  if(i%317==0){a.Destroy();b.Destroy();assert(b.ModelsByName.empty());}
 }
 a.Destroy();b.Destroy();assert(b.ModelsByName.empty());printf("ModelPool: %u lookup checks across 10000 register/duplicate/discard/destroy operations\n",checks);
}
'''
(out/'model_lifecycle.cpp').write_text(s,encoding="utf-8")
# Run the complete changed container cleanup and Compact bodies, not a parallel
# implementation of their iterator algorithm. Rendering and locks are shims.
s=common+r'''
#include <set>
using u16=unsigned short;using u32=unsigned;template<class T>using xr_vector=std::vector<T>;
#define VERIFY(x) assert(x)
#define R_ASSERT(x) assert(x)
struct FakeItem{u16 id;unsigned group;bool alive=true;u16 object_id(){assert(alive);return id;}};using PIItem=FakeItem*;
struct CUICellItem;
struct CUIWindow{using WINDOW_LIST=std::vector<CUIWindow*>;virtual CUICellItem*ui_cast_cell_item(){return nullptr;}virtual~CUIWindow()=default;};
static unsigned destroyed=0,redraws=0;
struct CUICellItem:CUIWindow{std::vector<CUICellItem*>m_childs;void*m_pData=nullptr;bool owner=true,m_b_destroy_childs=true;
 ~CUICellItem(){++destroyed;}CUICellItem*ui_cast_cell_item()override{return this;}bool IsAutoDelete(){return false;}u32 ChildsCount(){return u32(m_childs.size());}CUICellItem*Child(u32 i){return m_childs[i];}void SetOwnerList(void*p){owner=p!=nullptr;}void UpdateItemText(){assert(static_cast<FakeItem*>(m_pData)->alive);++redraws;}
 CUICellItem*PopChild(CUICellItem*);CUICellItem*PopChildForDestroy();};
struct CUICell{CUICellItem*m_item=nullptr;void Clear(){m_item=nullptr;}};
struct xrCriticalSectionGuard{explicit xrCriticalSectionGuard(int){}};
template<class T>void delete_data(T*&p){delete p;p=nullptr;}
struct CUICellContainer{int csUi=0;CUIWindow::WINDOW_LIST m_ChildWndList;std::vector<CUICell>m_cells;
 auto&GetChildWndList(){return m_ChildWndList;}void DetachChild(CUIWindow*p){auto i=std::find(m_ChildWndList.begin(),m_ChildWndList.end(),p);assert(i!=m_ChildWndList.end());m_ChildWndList.erase(i);}
 void ClearAll(bool,xr_vector<u16> ignored={});};
struct CUIDragDropListEx{CUICellContainer*m_container;void ClearAll(bool destroy){m_container->ClearAll(destroy);}void Compact();
 void SetItem(CUICellItem*item){assert(!item->ChildsCount());for(auto*w:m_container->m_ChildWndList){auto*r=w->ui_cast_cell_item();if(static_cast<FakeItem*>(r->m_pData)->group==static_cast<FakeItem*>(item->m_pData)->group){r->m_childs.push_back(item);return;}}m_container->m_ChildWndList.push_back(item);}
};
'''
s+=body(read('src/xrGame/ui/UICellItem.cpp',True),'CUICellItem* CUICellItem::PopChild(CUICellItem* needed)')+'\n'
s+=body(read('src/xrGame/ui/UICellItem.cpp'),'CUICellItem* CUICellItem::PopChildForDestroy()')+'\n'
s+=body(read('src/xrGame/ui/UIDragDropListEx.cpp'),'void CUICellContainer::ClearAll(bool bDestroy, xr_vector<u16> IgnoredItemsIds)')+'\n'
s+=body(read('src/xrGame/ui/UIDragDropListEx.cpp'),'void CUIDragDropListEx::Compact()')+'\n'
s+=r'''
std::multiset<u16> ids(CUICellContainer&c){std::multiset<u16>s;for(auto*w:c.m_ChildWndList){auto*r=w->ui_cast_cell_item();s.insert(static_cast<FakeItem*>(r->m_pData)->id);for(auto*child:r->m_childs)s.insert(static_cast<FakeItem*>(child->m_pData)->id);}return s;}
int main(){unsigned cases=0;for(unsigned n=0;n<32;++n)for(unsigned ignored=0;ignored<4;++ignored){
 CUICellContainer c;std::vector<FakeItem>game(256);unsigned used=0;std::multiset<u16>kept;
 for(unsigned i=0;i<n;++i){auto*r=new CUICellItem;game[used]={u16(used),i%3};r->m_pData=&game[used++];c.m_ChildWndList.push_back(r);c.m_cells.push_back({r});for(unsigned j=0;j<i%5;++j){auto*x=new CUICellItem;game[used]={u16(used),i%3};x->m_pData=&game[used++];r->m_childs.push_back(x);}}
 if(!ignored){CUIDragDropListEx list{&c};auto before=ids(c);for(unsigned repeat=0;repeat<5;++repeat){list.Compact();assert(ids(c)==before);}++cases;}
 std::vector<u16>ignore;
 if(ignored)for(size_t i=0;i<c.m_ChildWndList.size();++i)if(i%4==ignored-1){auto*r=c.m_ChildWndList[i]->ui_cast_cell_item();ignore.push_back(static_cast<FakeItem*>(r->m_pData)->id);kept.insert(static_cast<FakeItem*>(r->m_pData)->id);for(auto*x:r->m_childs)kept.insert(static_cast<FakeItem*>(x->m_pData)->id);}
 if(!ignored)for(auto&item:game)item.alive=false;
 unsigned beforeDestroyed=destroyed,beforeRedraws=redraws;
 c.ClearAll(true,ignore);assert(redraws==beforeRedraws);assert(ids(c)==kept);assert(destroyed-beforeDestroyed==used-kept.size());
 for(auto&item:game)item.alive=true;c.ClearAll(true);assert(c.m_ChildWndList.empty());++cases;
 }
 printf("Container cleanup: %u exact-body grouped/ignored/stale-data/repeated-Compact fixtures\n",cases);
}
'''
(out/'container_cleanup.cpp').write_text(s,encoding="utf-8")
