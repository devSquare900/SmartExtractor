import requests

try:
    docs = requests.get('http://127.0.0.1:8000/api/documents').json()
    if docs:
        doc = docs[0]
        doc_id = doc['doc_id']
        print(f"Doc: {doc['filename']}")
        ocr = requests.get(f'http://127.0.0.1:8000/api/documents/{doc_id}/ocr').json()
        pages = ocr.get('pages', [])
        print(f"Pages: {len(pages)}")
        if pages:
            print(f"Blocks on page 1: {len(pages[0].get('blocks', []))}")
            for b in pages[0].get('blocks', [])[:5]:
                print(b['text'])
except Exception as e:
    print(e)
