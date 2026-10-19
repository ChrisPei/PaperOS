"""Exercise the native comparator's actual ordering and stable selection IDs."""
from pathlib import Path
import os,subprocess,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]

class StoreRankingTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','Native C validation runs in Linux/WSL')
    def test_missing_metrics_ties_and_sort_modes(self):
        with tempfile.TemporaryDirectory(prefix='paperos-ranking-') as folder:
            work=Path(folder);source=work/'check.c';binary=work/'check'
            source.write_text(r'''
#include "store.h"
#include <assert.h>
#include <string.h>
int main(void){
    PaperOSStoreEntry popular={.key="a:popular",.name="Zulu",.stars=624,.updated="2025-01-01"};
    PaperOSStoreEntry recent={.key="a:recent",.name="Alpha",.stars=3,.updated="2026-10-19"};
    PaperOSStoreEntry unknown={.key="a:unknown",.name="Unknown",.stars=-1};
    PaperOSStoreEntry zero={.key="a:zero",.name="Zero",.stars=0};
    assert(paperos_store_compare(&popular,&recent,0)<0);
    assert(paperos_store_compare(&popular,&recent,1)>0);
    assert(paperos_store_compare(&popular,&recent,2)>0);
    assert(paperos_store_compare(&zero,&unknown,0)<0);
    PaperOSStoreEntry tie=popular;strcpy(tie.key,"b:popular");
    assert(paperos_store_compare(&popular,&tie,0)<0);
    assert(paperos_store_compare(&tie,&popular,0)>0);
    assert(!paperos_store_compare(&popular,&popular,0));
    popular.stars=recent.stars;
    assert(paperos_store_compare(&popular,&recent,0)>0);
    return 0;
}
''')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'native'),str(source),str(ROOT/'native/store_order.c'),'-o',str(binary)],check=True,capture_output=True)
            subprocess.run([str(binary)],check=True,capture_output=True)

if __name__=='__main__':unittest.main()
