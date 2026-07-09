

import unittest

from main import _strip_naming_command


class StripNamingCommandTests(unittest.TestCase):
    def test_bare_name_passes_through(self):
                                                                   
                                    
        self.assertEqual(_strip_naming_command("vibing"), "vibing")

    def test_save_the_audio_recording_to_X(self):
                                                 
        self.assertEqual(
            _strip_naming_command("save the audio recording to vibing"),
            "vibing",
        )

    def test_save_the_recording_as_X(self):
        self.assertEqual(
            _strip_naming_command("save the recording as holiday memories"),
            "holiday memories",
        )

    def test_save_the_audio_as_X(self):
        self.assertEqual(
            _strip_naming_command("save the audio as trip notes"),
            "trip notes",
        )

    def test_save_this_video_as_X(self):
        self.assertEqual(
            _strip_naming_command("save this video as graduation 2026"),
            "graduation 2026",
        )

    def test_save_the_image_as_X(self):
        self.assertEqual(
            _strip_naming_command("save the image as profile pic"),
            "profile pic",
        )

    def test_save_the_file_as_X(self):
        self.assertEqual(
            _strip_naming_command("save the file as resume"),
            "resume",
        )

    def test_call_it_X(self):
        self.assertEqual(
            _strip_naming_command("call it tax 2025"),
            "tax 2025",
        )

    def test_name_it_X(self):
        self.assertEqual(
            _strip_naming_command("name it project alpha"),
            "project alpha",
        )

    def test_save_it_as_X(self):
        self.assertEqual(
            _strip_naming_command("save it as the budget"),
            "the budget",
        )

    def test_as_X(self):
                                                             
        self.assertEqual(
            _strip_naming_command("as the gym playlist"),
            "the gym playlist",
        )

    def test_trailing_period_stripped(self):
                                                                  
                                                   
        self.assertEqual(
            _strip_naming_command("vibing."),
            "vibing",
        )
        self.assertEqual(
            _strip_naming_command("save the recording as holiday memories."),
            "holiday memories",
        )

    def test_empty_input_returns_empty(self):
        self.assertEqual(_strip_naming_command(""), "")
        self.assertEqual(_strip_naming_command(None), "")

    def test_unmatched_phrase_passes_through(self):
                                                                   
                                                                    
        self.assertEqual(
            _strip_naming_command("hello there friend"),
            "hello there friend",
        )

    def test_multi_word_name_preserved(self):
                                                                     
                                
        self.assertEqual(
            _strip_naming_command(
                "save the audio recording to my favourite song ever",
            ),
            "my favourite song ever",
        )


if __name__ == "__main__":
    unittest.main()
