from helpers import FIXTURES, OWNER  # sets import path and synthetic config
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from source_evidence import PageText, approved, normalize, source_key, verify_evidence


class EvidenceTests(unittest.TestCase):
    def test_url_allowlist(self):
        for url in ["http://docs.snowflake.com/", "https://docs.snowflake.com.evil.test/", "https://user:pass@docs.snowflake.com/", "https://docs.snowflake.com:8080/"]:
            with self.assertRaises(ValueError):
                approved(url)

    def test_parser_excludes_active_content(self):
        parser = PageText()
        parser.feed('<h1>Real &amp; useful</h1><script>wrong</script><style>wrong</style><p>Source text</p>')
        self.assertEqual(normalize(' '.join(parser.parts)), 'Real & useful Source text')

    def test_captured_quote_and_tamper_checks(self):
        url = 'https://docs.snowflake.com/example'
        quote = 'These reports require Enterprise Edition or higher.'
        raw = f'<p>{quote}</p>'.encode()
        data = {'post_url': url, 'features': [{'title': 'Example', 'classification': 'public', 'impact': {'kind': 'measure'}, 'sources': [{'url': url, 'excerpt': quote}]}]}
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            key = source_key(url)
            record = {'url': url, 'final_url': url, 'status': 200, 'content_type': 'text/html', 'text': quote, 'sha256': hashlib.sha256(raw).hexdigest()}
            (directory / f'{key}.raw').write_bytes(raw)
            (directory / f'{key}.json').write_text(json.dumps(record))
            verify_evidence(data, directory)
            data['features'][0]['sources'][0]['excerpt'] = 'This paraphrase was not present in the actual source.'
            with self.assertRaises(ValueError):
                verify_evidence(data, directory)
            data['features'][0]['sources'][0]['excerpt'] = quote
            (directory / f'{key}.raw').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                verify_evidence(data, directory)


if __name__ == '__main__':
    unittest.main()