"""Build differential tests from actual before/after source function bodies."""
from pathlib import Path
import subprocess, sys
engine=Path(sys.argv[1] if len(sys.argv)>1 else 'ixray').resolve()
out=Path(sys.argv[2] if len(sys.argv)>2 else 'work/tests').resolve();out.mkdir(parents=True,exist_ok=True)
def body(text, signature):
 start=text.index(signature);a=text.index('{',start);depth=1;i=a+1
 # These extracted methods have no braces inside string literals/comments.
 while depth:
  if text[i]=='{':depth+=1
  elif text[i]=='}':depth-=1
  i+=1
 return text[start:i]
def text(path,old=False):
 b=subprocess.check_output(['git','-C',str(engine),'show','HEAD:'+path]) if old else (engine/path).read_bytes()
 return b.decode('latin1').replace('\r\n','\n')
# HEAD in CI is pristine r1.3.6; these pure methods were unchanged by PR15.
old=body(text('src/xrScripts/script_storage.cpp',True),'bool CScriptStorage::object\t(LPCSTR identifier, int type)')
new=body(text('src/xrScripts/script_storage.cpp'),'bool CScriptStorage::object\t(LPCSTR identifier, int type)')
common=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <chrono>
#include <string>
extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}
#define VERIFY(x) assert(x)
#define xr_strcmp std::strcmp
using LPCSTR=const char*;
'''
for src,name in [(old,'old_lookup'),(new,'new_lookup')]:
 common+=src.replace('bool CScriptStorage::object\t(LPCSTR identifier, int type)',f'bool {name}(lua_State* L, LPCSTR identifier, int type)').replace('lua()','L')+'\n'
common+=r'''
static int metamethodCalls=0;
static int index_error(lua_State* L) { ++metamethodCalls; return luaL_error(L,"unexpected __index"); }
static int function(lua_State*) {return 0;}
int main() {
 lua_State* L=luaL_newstate();assert(L);luaL_openlibs(L);
 unsigned checked=0;
 for(int n: {0,1,10,100,1000}) {
  lua_newtable(L);int table=lua_gettop(L);
  for(int i=0;i<n;i++) {std::string k="key_"+std::to_string(i);lua_pushinteger(L,i);lua_setfield(L,table,k.c_str());}
  lua_pushcfunction(L,function);lua_setfield(L,table,"target");
  lua_newtable(L);lua_pushcfunction(L,index_error);lua_setfield(L,-2,"__index");lua_setmetatable(L,table);
  for(auto key: {"target","key_0","missing"}) for(int type: {LUA_TFUNCTION,LUA_TNUMBER,LUA_TSTRING,LUA_TNIL}) {
   int top=lua_gettop(L);lua_pushvalue(L,table);bool a=old_lookup(L,key,type);assert(lua_gettop(L)==top);
   lua_pushvalue(L,table);bool b=new_lookup(L,key,type);assert(lua_gettop(L)==top);assert(a==b);++checked;
  }
  // Mutation between lookups is observed; no functor or namespace cache.
  lua_pushnil(L);lua_setfield(L,table,"target");lua_pushvalue(L,table);assert(!new_lookup(L,"target",LUA_TFUNCTION));
  lua_pushcfunction(L,function);lua_setfield(L,table,"target");lua_pushvalue(L,table);assert(new_lookup(L,"target",LUA_TFUNCTION));
  lua_settop(L,0);
 }
 // The legacy numeric-key alias still succeeds; fallback uses the original scan.
 lua_newtable(L);lua_pushcfunction(L,function);lua_rawseti(L,-2,17);
 lua_pushvalue(L,-1);assert(old_lookup(L,"17",LUA_TFUNCTION));
 lua_pushvalue(L,-1);assert(new_lookup(L,"17",LUA_TFUNCTION));lua_settop(L,0);
 assert(metamethodCalls==0);
 printf("Lua differential cases: %u; stack/mutation/numeric-alias/__index checks passed\n",checked);
 for(int n: {100,1000,10000}) {
  lua_newtable(L);int table=lua_gettop(L);
  for(int i=0;i<n;i++) {std::string key="item"+std::to_string(i);lua_pushcfunction(L,function);lua_setfield(L,table,key.c_str());}
  lua_pushcfunction(L,function);lua_setfield(L,table,"target");
  constexpr int runs=10000;
  auto measure=[&](auto fn){auto start=std::chrono::steady_clock::now();for(int i=0;i<runs;i++){lua_pushvalue(L,table);assert(fn(L,"target",LUA_TFUNCTION));}return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();};
  printf("Lua synthetic entries=%d lookups=%d old_ms=%.6f new_ms=%.6f\n",n,runs,measure(old_lookup),measure(new_lookup));lua_settop(L,0);
 }
 lua_close(L);
}
'''
(out/'lua_lookup.cpp').write_text(common,encoding='utf-8')
# File-list tests compile the actual old/new implementation and PatternMatch.
filetext=text('src/xrCore/LocatorAPI.cpp');oldfile=text('src/xrCore/LocatorAPI.cpp',True)
old=body(oldfile,'int CLocatorAPI::file_list(').replace('CLocatorAPI::file_list','CLocatorAPI::old_list')
new=body(filetext,'int CLocatorAPI::file_list(').replace('CLocatorAPI::file_list','CLocatorAPI::new_list')
pattern=body(text('src/xrCore/LocatorAPI_defs.cpp'),'bool XRCORE_API PatternMatch(').replace('XRCORE_API ','')
common=r'''
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <set>
#include <random>
#include <chrono>
#define R_ASSERT(x) assert(x)
#define VERIFY(x) assert(x)
using u32=unsigned;using LPCSTR=const char*;using BOOL=bool;using string_path=char[1024];
using xr_string=std::string;using SStringVec=std::vector<std::string>;using SStringVecIt=SStringVec::iterator;
#define xr_strlen std::strlen
#define xr_strcpy(dst,sz,src) (assert(std::strlen(src)<sz),std::strcpy(dst,src))
constexpr u32 FS_ListFiles=1,FS_ListFolders=2,FS_ClampExt=4,FS_RootOnly=8;
struct FS_File {enum {flVFS=1,flSubDir=2};std::string name;u32 size=0;long long time_write=0;u32 attrib=0;
 FS_File()=default; FS_File(const char*n,u32 s,long long t,u32 a):name(n),size(s),time_write(t),attrib(a){}
 bool operator<(const FS_File& x) const{return name<x.name;}
 bool operator==(const FS_File&)const=default;
};
using FS_FileSet=std::set<FS_File>;
struct {std::string ChangeFileExt(std::string n,const char*){auto p=n.rfind('.');if(p!=std::string::npos)n.resize(p);return n;}} EFS;
void _SequenceToList(SStringVec& v,const char* mask){if(!mask)return;std::string s=mask;size_t a=0;while(a<=s.size()){auto b=s.find(',',a);auto x=s.substr(a,b-a);auto l=x.find_first_not_of(" \t"),r=x.find_last_not_of(" \t");if(l!=std::string::npos)v.push_back(x.substr(l,r-l+1));if(b==s.npos)break;a=b+1;}}
struct CLocatorAPI {struct file {LPCSTR name;u32 vfs=0xffffffff, size_real=1;long long modif=7;};
 struct pred {bool operator()(const file&a,const file&b)const{return std::strcmp(a.name,b.name)<0;}};
 using files_set=std::set<file,pred>;using files_it=files_set::iterator;files_set m_files;
 void check_pathes(){} bool path_exist(const char*){return false;}
 void update_path(char* dst,const char* src,const char*){std::strcpy(dst,src);}
 int old_list(FS_FileSet&,LPCSTR,u32,LPCSTR);int new_list(FS_FileSet&,LPCSTR,u32,LPCSTR);
};
'''+pattern+'\n'+old+'\n'+new+r'''
int main(){
 std::set<std::string> names={"configs\\","configs\\scripts\\","configs\\scripts\\dummy.ltx","configs\\scripts\\a.ltx","configs\\scripts\\alpha.ltx","configs\\scripts\\alpha_extra.ltx","configs\\scripts\\mod_alpha_one.ltx","configs\\scripts\\mod_alpha_extra_one.ltx","configs\\scripts\\sub\\","configs\\scripts\\sub\\nested.ltx","configs\\scripts\\sub\\mod_alpha_one.ltx","other\\"};
 for(int i=0;i<4000;i++)names.insert("configs\\scripts\\entry_"+std::to_string(i)+".ltx");
 CLocatorAPI fs;for(const auto& name:names)fs.m_files.insert({name.c_str()});
 unsigned cases=0;
 for(const char* path:{"configs\\","configs\\scripts\\","configs\\scripts\\sub\\","missing\\"})
 for(u32 flags=1;flags<16;flags++)
 for(const char* mask:{"*","*.ltx","mod_alpha_*.ltx","alpha_*.ltx","alpha.ltx","a?pha*.ltx","*alpha*","sub\\*.ltx","MISSING*","mod_*.ltx,alpha*","","?","..*","\\*","alpha[1]*"}){
  FS_FileSet a,b;FS_File prior;prior.name="retained";a.insert(prior);b.insert(prior);
  auto ra=fs.old_list(a,path,flags,mask),rb=fs.new_list(b,path,flags,mask);
  assert(ra==rb);assert(a==b);++cases;
 }
 std::mt19937 rng(42);const std::string alphabet="abc_mod123*?.\\";
 for(int run=0;run<10000;run++){
  std::string mask;for(unsigned i=0,n=rng()%16;i<n;i++)mask+=alphabet[rng()%alphabet.size()];
  FS_FileSet a,b;u32 flags=1+rng()%15;fs.old_list(a,"configs\\scripts\\",flags,mask.c_str());fs.new_list(b,"configs\\scripts\\",flags,mask.c_str());assert(a==b);++cases;
 }
 printf("Filesystem differential cases: %u (all flag combinations, existing destination, recursion, multiple masks, random masks)\n",cases);
 auto measure=[&](auto fn){auto start=std::chrono::steady_clock::now();for(int i=0;i<2000;i++){FS_FileSet dest;(fs.*fn)(dest,"configs\\scripts\\",FS_ListFiles,"mod_alpha_*.ltx");}return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();};
 printf("Filesystem synthetic entries=%zu lists=2000 old_ms=%.6f new_ms=%.6f\n",names.size(),measure(&CLocatorAPI::old_list),measure(&CLocatorAPI::new_list));
}
'''
(out/'filesystem.cpp').write_text(common,encoding='utf-8')
print(out)
oldini=text('src/xrCore/Xr_ini.cpp',True);newini=text('src/xrCore/Xr_ini.cpp')
def regex_block(s):
 a=s.index('\t\t\tauto GetRegexMatch =');b=s.index('\n\t\t\tcontinue;',a)
 return s[a:b]
common=r'''
#undef NDEBUG
#include <cassert>
#include <cstdio>
#include <vector>
#include <map>
#include <regex>
#include <string>
#include <chrono>
using xr_string=std::string;template<class K,class V>using xr_map=std::map<K,V>;
struct FS_File {std::string name;};
'''
for s,name in [(oldini,'old_regex'),(newini,'new_regex')]:
 common+='std::vector<std::string> '+name+'(const std::vector<FS_File>& ModFiles,const std::vector<FS_File>& AmbiguousFiles) {\nstd::vector<std::string> result;std::string FilePath="configs\\\\";auto loadFile=[&](auto,auto,auto name){result.push_back(name);};\n'+regex_block(s)+'\nreturn result;\n}\n'
common+=r'''
int main(){
 unsigned cases=0;
 std::vector<FS_File> mods={{"mod_alpha_one.ltx"},{"mod_alpha_sub_one.ltx"},{"mod_alpha_xxx.ltx"},{"mod_alpha_file[1]_one.ltx"},{"mod_alpha_.ltx"},{"sub\\mod_alpha_sub_one.ltx"}};
 std::vector<FS_File> ambiguous={{"alpha_sub.ltx"},{"alpha_file[1].ltx"},{"alpha.file.ltx"},{"sub\\alpha_sub.ltx"}};
 for(unsigned mask=0;mask<(1u<<mods.size());++mask) for(unsigned am=0;am<(1u<<ambiguous.size());++am){
  std::vector<FS_File> m,a;for(unsigned i=0;i<mods.size();i++)if(mask&(1u<<i))m.push_back(mods[i]);for(unsigned i=0;i<ambiguous.size();i++)if(am&(1u<<i))a.push_back(ambiguous[i]);
  assert(old_regex(m,a)==new_regex(m,a));++cases;
 }
 printf("DLTX regex differential cases: %u; result and load order preserved\n",cases);
 auto measure=[&](auto fn){auto start=std::chrono::steady_clock::now();for(int i=0;i<500;i++)fn(mods,ambiguous);return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();};
 printf("DLTX synthetic passes=500 old_ms=%.6f new_ms=%.6f\n",measure(old_regex),measure(new_regex));
}
'''
(out/'regex.cpp').write_text(common,encoding='utf-8')
# Ensure Release cannot compile away assertions or calls under test.
for p in out.glob('*.cpp'):
 p.write_text('#undef NDEBUG\n'+p.read_text(encoding='utf-8'),encoding='utf-8')
# Preserve line_exist's exact-case gate, lowercase fallback, null/empty handling.
old=body(text('src/xrCore/Xr_ini.cpp',True),'BOOL CInifile::line_exist(').replace('CInifile::line_exist','CInifile::old_line')
new=body(text('src/xrCore/Xr_ini.cpp'),'BOOL CInifile::line_exist(').replace('CInifile::line_exist','CInifile::new_line')
common=r'''
#undef NDEBUG
#include <cassert>
#include <cstring>
#include <algorithm>
#include <vector>
#include <string>
#include <stdexcept>
#include <cstdio>
#include <cctype>
using LPCSTR=const char*;using BOOL=bool;
#define FALSE false
#define _strlwr mock_strlwr
#define xr_strcmp std::strcmp
#define xr_strcpy(dst,sz,src) (std::strlen(src)>=sz?throw std::runtime_error("length"):std::strcpy(dst,src))
char* mock_strlwr(char* s){for(char*p=s;*p;++p)*p=static_cast<char>(std::tolower(static_cast<unsigned char>(*p)));return s;}
struct Str {std::string s; const char*operator*()const{return s.c_str();}};
struct Item{Str first;};struct Sect{Str Name;std::vector<Item>Data;};
bool sect_pred(const Sect*a,LPCSTR b){return a->Name.s<b;}
bool item_pred(const Item&a,LPCSTR b){return a.first.s<b;}
struct CInifile {using RootCIt=std::vector<Sect*>::const_iterator;using SectCIt=std::vector<Item>::const_iterator;std::vector<Sect*>DATA;
 bool section_exist(LPCSTR s)const{if(!s)return false;auto i=std::lower_bound(DATA.begin(),DATA.end(),s,sect_pred);return i!=DATA.end()&&(*i)->Name.s==s;}
 Sect&r_section(LPCSTR s)const{if(!s||!*s)throw std::runtime_error("empty");char tmp[256];xr_strcpy(tmp,sizeof(tmp),s);_strlwr(tmp);auto i=std::lower_bound(DATA.begin(),DATA.end(),tmp,sect_pred);if(i==DATA.end()||(*i)->Name.s!=tmp)throw std::runtime_error("missing");return **i;}
 BOOL old_line(LPCSTR,LPCSTR)const;BOOL new_line(LPCSTR,LPCSTR)const;
};
'''+old+'\n'+new+r'''
int main(){
 Sect a{{""},{{{"key"}}}},b{{"UPPER"},{{{"key"}}}},c{{"Mixed"},{{{"key"}}}},d{{"mixed"},{{{"other"}}}},e{{"lower"},{{{"key"}},{{"other"}}}};
 CInifile ini;ini.DATA={&a,&b,&c,&d,&e};std::sort(ini.DATA.begin(),ini.DATA.end(),[](auto a,auto b){return a->Name.s<b->Name.s;});unsigned cases=0;
 for(const char*s:{static_cast<const char*>(nullptr),"","UPPER","upper","Mixed","mixed","lower","absent"})for(const char*l:{static_cast<const char*>(nullptr),"","key","other","missing"}){
  int old_result,new_result;try{old_result=ini.old_line(s,l);}catch(const std::runtime_error&){old_result=-1;}
  try{new_result=ini.new_line(s,l);}catch(const std::runtime_error&){new_result=-1;}
  assert(old_result==new_result);++cases;
 }
 printf("INI line_exist differential cases: %u; null/empty/case/missing and error paths preserved\n",cases);
}
'''
(out/'ini.cpp').write_text(common,encoding='utf-8')

# INI section finalization: compare exact old/new extracted implementations.
src=text('src/xrCore/Xr_ini.cpp')
old=body(text('src/xrCore/Xr_ini.cpp',True),'void CInifile::EvaluateSection(')
new=body(src,'void CInifile::EvaluateSection(')
# Count entered/effective evaluations without changing the function algorithm.
old=old.replace('CInifile::EvaluateSection','OldIni::EvaluateSection').replace('{\n\tstd::unordered_set','{\n    ++calls;\n\tstd::unordered_set',1)
new=new.replace('CInifile::EvaluateSection','NewIni::EvaluateSection').replace('\n\tPreviousEvaluations.push_back','\n    ++calls;\n\tPreviousEvaluations.push_back',1)
old=old.replace('CInifile::','OldIni::');new=new.replace('CInifile::','NewIni::')
merge=body(src,'void CInifile::MergeParentSet(').replace('CInifile::','Common::')
common=r'''
#undef NDEBUG
#include <algorithm>
#include <cassert>
#include <string>
#include <vector>
#include <unordered_set>
#include <unordered_map>
#include <map>
#include <cstdio>
#include <stdexcept>
#include <random>
#include <chrono>
#include <cstdarg>
using xr_string=std::string;template<class T>using xr_vector=std::vector<T>;template<class K,class V>using xr_string_map=std::unordered_map<K,V>;
using LPCSTR=const char*;using BOOL=bool;
#define TRUE true
#define FALSE false
#define DEBUG_INFO 0
constexpr const char* DLTX_DELETE="DLTX_DELETE";
struct Str {bool null=true;std::string s;Str()=default;Str(const char*p){*this=p;}
 Str&operator=(const char*p){null=!p;s=p?p:"";return*this;}
 const char*c_str()const{return null?nullptr:s.c_str();}const char*operator*()const{return c_str();}
 char operator[](size_t i)const{return s[i];}bool equal(const Str&o)const{return null==o.null&&s==o.s;}
 bool operator!=(std::nullptr_t)const{return!null;}
};using shared_str=Str;
struct DebugType {void fatal(int,const char*fmt,...){char buf[1024];va_list a;va_start(a,fmt);vsnprintf(buf,sizeof(buf),fmt,a);va_end(a);throw std::runtime_error(buf);}} Debug;
struct Common {
 struct Item{Str first,second;};struct Sect{Str Name;std::vector<Item>Data;};using SectIt_=std::vector<Item>::iterator;
 enum class InsertType{Override,Base,Parent};
 xr_string_map<std::string,Sect>FinalData,BaseData,OverrideData;
 xr_string_map<std::string,std::vector<std::string>>BaseParentDataMap,OverrideParentDataMap;
 xr_string_map<std::string,std::vector<Item>>OverrideModifyListData;
 const char*m_file_name="fixture.ltx",*DLTXCurrentFileName="fixture.ltx";unsigned long long calls=0;
 void MergeParentSet(std::vector<std::string>&,std::vector<std::string>&,bool);
 static bool item_pred(const Item&a,LPCSTR b){return a.first.s<b;}
};
struct OldIni:Common {void EvaluateSection(std::string,std::vector<std::string>&);};
struct NewIni:Common {void EvaluateSection(std::string,std::vector<std::string>&);};
'''+merge+'\n'+old+'\n'+new+r'''
using Snapshot=std::map<std::string,std::vector<std::pair<std::string,std::string>>>;
template<class Ini>std::pair<std::string,Snapshot> evaluate(Ini&ini){
 std::string error;try{std::vector<std::string> stack;for(const auto&[name,sect]:ini.BaseData)ini.EvaluateSection(name,stack);assert(stack.empty());}catch(const std::exception&e){error=e.what();}
 Snapshot snap;for(auto&[name,sect]:ini.FinalData){auto&vec=snap[name];for(const auto&item:sect.Data)vec.push_back({item.first.s,item.second.null?"<null>":item.second.s});}return{error,snap};
}
void add(Common&ini,std::string name,std::vector<std::pair<std::string,std::string>>data,std::vector<std::string>parents={}){
 Common::Sect s;s.Name=name.c_str();for(auto&[k,v]:data)s.Data.push_back({k.c_str(),v.c_str()});std::sort(s.Data.begin(),s.Data.end(),[](const auto&a,const auto&b){return a.first.s<b.first.s;});ini.BaseData[name]=s;ini.BaseParentDataMap[name]=parents;
}
int main(){
 unsigned checked=0;std::mt19937 rng(123);
 for(int test=0;test<2000;test++){
  Common fixture;
  for(int i=0;i<8;i++){
   std::string name="section"+std::to_string(i);std::vector<std::string>parents;
   for(int j=0;j<i;j++)if(rng()%4==0)parents.push_back("section"+std::to_string(j));
   std::vector<std::pair<std::string,std::string>>data;
   for(int k=0;k<3;k++)if(rng()%2)data.push_back({"key"+std::to_string(k),"value"+std::to_string(rng()%5)});
   data.push_back({"list","a,b,c"});add(fixture,name,data,parents);
   if(rng()%3==0){Common::Sect o;o.Name=name.c_str();o.Data.push_back({"key0",rng()%3==0?DLTX_DELETE:"override"});fixture.OverrideData[name]=o;}
   if(rng()%8==0)fixture.OverrideData[name].Data.push_back({DLTX_DELETE,nullptr});
   if(i&&rng()%3==0)fixture.OverrideParentDataMap[name].push_back("section"+std::to_string(rng()%i));
   if(i&&rng()%5==0)fixture.OverrideParentDataMap[name].push_back("!section"+std::to_string(rng()%i));
   if(rng()%3==0)fixture.OverrideModifyListData[name].push_back({rng()%2?">list":"<list","b,d"});
  }
  OldIni old;NewIni now;static_cast<Common&>(old)=fixture;static_cast<Common&>(now)=fixture;
  auto a=evaluate(old),b=evaluate(now);if(a!=b){printf("Mismatch fixture %d old_calls=%llu new_calls=%llu\n",test,old.calls,now.calls);return 1;}++checked;
 }

 for(int order=0;order<2;order++)for(int kind=0;kind<3;kind++){
  Common fixture;
  if(order==0){add(fixture,"empty",{});add(fixture,"child",{{"key","child"}},{"empty"});}
  else{add(fixture,"child",{{"key","child"}},{"empty"});add(fixture,"empty",{});}
  fixture.OverrideData["empty"].Data.push_back({DLTX_DELETE,nullptr});
  if(kind==1)fixture.OverrideParentDataMap["child"].push_back("empty");
  if(kind==2)fixture.OverrideModifyListData["empty"].push_back({">list","b,d"});
  OldIni old;NewIni now;static_cast<Common&>(old)=fixture;static_cast<Common&>(now)=fixture;
  assert(evaluate(old)==evaluate(now));++checked;
 }
 for(int mode=0;mode<4;mode++){
  Common fixture;add(fixture,"a",{{"key","a"}}, mode==0?std::vector<std::string>{"missing"}:std::vector<std::string>{"b"});add(fixture,"b",{{"key","b"}},mode==0?std::vector<std::string>{}:std::vector<std::string>{"a"});
  if(mode==2)fixture.OverrideData["a"].Data.push_back({DLTX_DELETE,nullptr});
  if(mode==3)fixture.OverrideParentDataMap["a"].push_back("!b");
  OldIni old;NewIni now;static_cast<Common&>(old)=fixture;static_cast<Common&>(now)=fixture;assert(evaluate(old)==evaluate(now));++checked;
 }
 Common fixture;add(fixture,"root",{{"key","data"}});
 // Shared-parent DAG: old traversal repeats completed ancestors exponentially.
 for(int level=1;level<=10;level++)for(int side=0;side<2;side++){
  std::string name="n"+std::to_string(level)+std::to_string(side);
  std::vector<std::string> parents=level==1?std::vector<std::string>{"root"}:std::vector<std::string>{"n"+std::to_string(level-1)+"0","n"+std::to_string(level-1)+"1"};add(fixture,name,{{"own",name}},parents);
 }
 OldIni old;NewIni now;static_cast<Common&>(old)=fixture;static_cast<Common&>(now)=fixture;
 auto start=std::chrono::steady_clock::now();auto a=evaluate(old);auto mid=std::chrono::steady_clock::now();auto b=evaluate(now);auto end=std::chrono::steady_clock::now();assert(a==b);
 printf("INI evaluation differential fixtures: %u; inheritance/overrides/deletions/list edits/cycles/errors and final values preserved\n",checked);
 printf("INI DAG synthetic sections=%zu old_evaluations=%llu new_evaluations=%llu old_ms=%.6f new_ms=%.6f\n",fixture.BaseData.size(),old.calls,now.calls,std::chrono::duration<double,std::milli>(mid-start).count(),std::chrono::duration<double,std::milli>(end-mid).count());
}
'''
(out/'ini_evaluation.cpp').write_text(common,encoding='utf-8')
