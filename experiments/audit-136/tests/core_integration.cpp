#undef NDEBUG
#include "xrCore.h"
#include <cassert>
#include <cstdio>
#include <sstream>
#include <random>
#include <string>

struct WritableIni : CInifile { using CInifile::CInifile; void writable() { m_flags.set(eReadOnly,FALSE);set_override_names(TRUE); } };
static unsigned long long digest=14695981039346656037ull;
static void hash(const char* s) { for(;*s;++s) { digest^=static_cast<unsigned char>(*s);digest*=1099511628211ull; }digest^=255;digest*=1099511628211ull; }
static void check(const std::string& text) {
 IReader reader(const_cast<char*>(text.data()),text.size());
 CInifile ini(&reader);
 std::string last;
 for(const auto*section:ini.sections()) {
  assert(last.empty()||last<*section->Name);last=*section->Name;
  hash(*section->Name);
  for(const auto&item:section->Data) {hash(*item.first);hash(item.second.c_str()?item.second.c_str():"<null>");}
 }
}
int main() {
 // In-memory roots with no includes do not need FS initialization or game assets.
 Memory._initialize();
 {
  const char* text="[base]\nkey = original\nlist = a,b,c\n[child]:base\nkey = child\n![base]\nkey = override\n";
  IReader reader(const_cast<char*>(text),strlen(text));WritableIni ini(&reader);ini.writable();
  assert(strcmp(ini.r_string("base","key"),"override")==0);
  assert(strcmp(ini.r_string("child","key"),"child")==0);
  assert(strcmp(ini.r_string("child","list"),"a,b,c")==0);
  // Public mutation is still observed; results are not cached across objects.
  ini.w_string("base","key","mutated");assert(strcmp(ini.r_string("base","key"),"mutated")==0);
 }
 std::mt19937 rng(904);
 for(unsigned test=0;test<2000;++test) {
  std::ostringstream text;
  for(unsigned i=0;i<12;++i) {
   text<<"[s"<<i<<"]";
   if(i) { text<<":s"<<(rng()%i);if(i>2&&rng()%2)text<<",s"<<(rng()%i); }
   text<<"\nkey"<<(rng()%4)<<" = value"<<(rng()%8)<<"\nlist = a,b,c\n";
  }
  for(unsigned i=0;i<12;++i)if(rng()%3==0)text<<"![s"<<i<<"]\nkey0 = override\n";
  check(text.str());
 }
 printf("Actual xrCore CInifile: 2000 full in-memory parse/inheritance/override fixtures; digest=%016llx\n",digest);
 // Process exit frees the DLL's global objects; no game filesystem or renderer used.
 return 0;
}
