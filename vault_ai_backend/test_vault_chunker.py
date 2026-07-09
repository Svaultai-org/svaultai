

from __future__ import annotations

import unittest

from vault_chunker import (
    Chunk,
    chunk_extracted_text,
    chunks_to_dicts,
    DEFAULT_TARGET_CHARS,
    DEFAULT_OVERLAP_CHARS,
    MAX_CHUNK_CHARS,
)


class EmptyInputTests(unittest.TestCase):
    def test_empty_string_returns_no_chunks(self):
        self.assertEqual(
            chunk_extracted_text("", extraction_source="pdf_text"),
            [],
        )

    def test_whitespace_only_returns_no_chunks(self):
        self.assertEqual(
            chunk_extracted_text(" \n\t  \n", extraction_source="pdf_text"),
            [],
        )

    def test_text_shorter_than_target_returns_one_chunk(self):
        chunks = chunk_extracted_text(
            "Hello world.", extraction_source="pdf_text",
        )
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "Hello world.")
        self.assertEqual(chunks[0].chunk_index, 0)

    def test_invalid_target_chars_raises(self):
        with self.assertRaises(ValueError):
            chunk_extracted_text("x", extraction_source="x", target_chars=0)

    def test_invalid_overlap_raises(self):
        with self.assertRaises(ValueError):
            chunk_extracted_text(
                "x", extraction_source="x",
                target_chars=100, overlap_chars=100,
            )
        with self.assertRaises(ValueError):
            chunk_extracted_text(
                "x", extraction_source="x",
                target_chars=100, overlap_chars=-1,
            )


class StructuralTests(unittest.TestCase):
    def test_chunks_have_monotonic_indices_from_zero(self):
        text = "Para one. " * 500
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=200, overlap_chars=20,
        )
        for i, c in enumerate(chunks):
            self.assertEqual(c.chunk_index, i)

    def test_char_ranges_are_within_text_length(self):
        text = "Para one. " * 500
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=200, overlap_chars=20,
        )
        for c in chunks:
            self.assertGreaterEqual(c.char_start, 0)
            self.assertGreater(c.char_end, c.char_start)
            self.assertLessEqual(c.char_end, len(text))
            self.assertEqual(c.char_length, c.char_end - c.char_start)

    def test_char_ranges_make_forward_progress(self):
                                                                
                                                                    
        text = "Para one. " * 500
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=200, overlap_chars=50,
        )
        for prev, cur in zip(chunks, chunks[1:]):
            self.assertLess(prev.char_start, cur.char_start)

    def test_extraction_source_round_trips(self):
        for source in (
            "pdf_text", "ocr", "image_ocr", "docx", "txt",
            "html", "json", "csv", "xlsx", "archive",
            "audio_transcript", "video_transcript",
        ):
            chunks = chunk_extracted_text(
                "Lorem ipsum.", extraction_source=source,
            )
            self.assertGreater(len(chunks), 0)
            self.assertEqual(chunks[0].extraction_source, source)


class BoundaryPreferenceTests(unittest.TestCase):
    def test_prefers_paragraph_break(self):
                                                                    
                                                                  
        text = ("A " * 60) + "\n\n" + ("B " * 60)
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=140, overlap_chars=20,
        )
                                                                   
                          
        self.assertNotIn("B ", chunks[0].text)
                                                      
        self.assertIn("B ", chunks[1].text)

    def test_prefers_sentence_end_when_no_paragraph(self):
                                                                   
                     
        s1 = "First sentence is about taxes."
        s2 = "Second sentence is about insurance."
        text = (s1 + " ") * 5 + s2
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=80, overlap_chars=10,
        )
                                                                
                    
        any_ends_at_period = any(c.text.rstrip().endswith(".")
                                 for c in chunks)
        self.assertTrue(any_ends_at_period)

    def test_word_boundary_fallback(self):
                                                                     
                                                                  
        text = " ".join([f"word{i:03d}" for i in range(200)])
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=150, overlap_chars=20,
        )
        for c in chunks[:-1]:                                     
                                                                      
                                                 
            self.assertRegex(c.text, r"word\d{3}$")


class CapTests(unittest.TestCase):
    def test_every_chunk_under_max_chunk_chars(self):
                                                                
                                                                 
        text = "x" * (MAX_CHUNK_CHARS * 3)
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=1500, overlap_chars=100,
            max_chunk_chars=MAX_CHUNK_CHARS,
        )
        self.assertGreater(len(chunks), 0)
        for c in chunks:
            self.assertLessEqual(c.char_length, MAX_CHUNK_CHARS)

    def test_default_constants_are_sane(self):
        self.assertGreater(DEFAULT_TARGET_CHARS, 0)
        self.assertGreaterEqual(DEFAULT_OVERLAP_CHARS, 0)
        self.assertLess(DEFAULT_OVERLAP_CHARS, DEFAULT_TARGET_CHARS)
        self.assertGreaterEqual(MAX_CHUNK_CHARS, DEFAULT_TARGET_CHARS)


class RoundTripTests(unittest.TestCase):
    def test_chunk_text_is_substring_of_source(self):
        text = (
            "The blue contract expires on 2027-08-19. "
            * 50
        )
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=200, overlap_chars=30,
        )
        for c in chunks:
                                                                
                                                                  
            self.assertIn(c.text, text)

    def test_chunks_to_dicts_round_trip(self):
        text = "Para one. " * 100
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=200, overlap_chars=20,
        )
        dicts = chunks_to_dicts(chunks)
        self.assertEqual(len(dicts), len(chunks))
        for c, d in zip(chunks, dicts):
            self.assertEqual(d["chunk_index"], c.chunk_index)
            self.assertEqual(d["char_start"], c.char_start)
            self.assertEqual(d["char_end"], c.char_end)
            self.assertEqual(d["text"], c.text)
            self.assertEqual(d["extraction_source"], c.extraction_source)


class SentinelRetrievalTests(unittest.TestCase):


    SENTINEL = "The blue contract expires on 2027-08-19."

    def test_sentinel_lands_in_some_chunk(self):
        prefix = "Filler paragraph. " * 200
        suffix = " More filler. " * 200
        text = prefix + self.SENTINEL + suffix
        chunks = chunk_extracted_text(
            text, extraction_source="pdf_text",
            target_chars=1500, overlap_chars=200,
        )
        contains_sentinel = [c for c in chunks if self.SENTINEL in c.text]
        self.assertGreater(
            len(contains_sentinel), 0,
            f"sentinel must appear in at least one chunk; chunks={len(chunks)}",
        )


if __name__ == "__main__":
    unittest.main()
