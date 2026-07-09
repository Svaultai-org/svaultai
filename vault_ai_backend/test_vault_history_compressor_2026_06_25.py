

from __future__ import annotations

import json
import unittest

import vault_history_compressor as vhc


def _msg(role, content):
    return {"role": role, "content": content}


class NoCompressionForShortHistory(unittest.TestCase):
    def test_two_turn_conversation_passes_through(self):
        messages = [
            _msg("system", "STATIC"),
            _msg("user", "hi"),
            _msg("assistant", "hello"),
            _msg("user", "what can you do"),
            _msg("assistant", "lots of things"),
        ]
        out = vhc.compress_messages(messages)
        self.assertFalse(out.compression_summary["compressed"])
        self.assertIsNone(out.memory_message)
        self.assertEqual(out.recent_messages, messages[1:])

    def test_exactly_five_turns_no_compression(self):
        msgs = [_msg("system", "STATIC")]
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
                                                
        self.assertFalse(out.compression_summary["compressed"])


class CompressionActivates(unittest.TestCase):
    def _ten_turn_convo(self):
        msgs = [_msg("system", "STATIC")]
        for i in range(10):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        return msgs

    def test_ten_turn_history_drops_to_five_recent(self):
        msgs = self._ten_turn_convo()
        out = vhc.compress_messages(msgs)
        self.assertTrue(out.compression_summary["compressed"])
                                              
        self.assertEqual(len(out.recent_messages), 10)
                                                          
        self.assertEqual(
            out.compression_summary["summarized_count"], 10,
        )

    def test_head_messages_preserved_unchanged(self):
        msgs = self._ten_turn_convo()
        out = vhc.compress_messages(msgs)
        self.assertEqual(len(out.head), 1)
        self.assertEqual(out.head[0]["role"], "system")
        self.assertEqual(out.head[0]["content"], "STATIC")


class SecretStrippingFloor(unittest.TestCase):
    def _convo_with_secrets(self):
                                                                 
                                                                 
        msgs = [_msg("system", "STATIC")]
        msgs.append(_msg("user",
            "create a username and password for Chase"))
        msgs.append(_msg("assistant",
            "username: riverfox472\npassword: Strong!!Pass99"))
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        return msgs

    def test_password_value_never_in_memory_block(self):
        msgs = self._convo_with_secrets()
        out = vhc.compress_messages(msgs)
        self.assertTrue(out.compression_summary["compressed"])
        memory = out.memory_message["content"]
        self.assertNotIn("Strong!!Pass99", memory)

    def test_pin_value_stripped(self):
        msgs = [
            _msg("system", "STATIC"),
            _msg("user", "my PIN is 654321 don't share"),
            _msg("assistant", "noted"),
        ]
                                                           
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
        memory = out.memory_message["content"] if out.memory_message else ""
        self.assertNotIn("654321", memory)

    def test_seed_phrase_stripped(self):
        msgs = [
            _msg("system", "STATIC"),
            _msg("user",
                "seed phrase: alpha beta gamma delta epsilon zeta"),
            _msg("assistant", "saved"),
        ]
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
        memory = out.memory_message["content"] if out.memory_message else ""
        self.assertNotIn("alpha beta gamma", memory)

    def test_token_value_stripped(self):
        msgs = [
            _msg("system", "STATIC"),
            _msg("user", "access_token: ghp_aaaaBBBBccccDDDD12345678"),
            _msg("assistant", "noted"),
        ]
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
        memory = out.memory_message["content"] if out.memory_message else ""
        self.assertNotIn("ghp_aaaaBBBBccccDDDD12345678", memory)


class PreservedSignals(unittest.TestCase):
    def test_credential_draft_recorded_as_pending_draft(self):
        msgs = [
            _msg("system", "STATIC"),
            _msg("user", "create a username and password for Union Bank"),
            _msg("assistant",
                "Here is one for you:\n"
                "username: northmark91\n"
                "password: Sec!ureWord77"),
        ]
                                          
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
        memory = out.memory.pending_drafts
                                                          
        joined = " | ".join(memory)
        self.assertIn("Union Bank", joined)

    def test_save_it_now_recorded_as_pending_confirmation(self):
        msgs = [
            _msg("system", "STATIC"),
            _msg("user", "save it now"),
            _msg("assistant", "Acknowledging — saving."),
        ]
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
        joined = " | ".join(out.memory.pending_confirmations)
        self.assertIn("save it now", joined.lower())

    def test_use_option_1_recorded_as_pending_confirmation(self):
        msgs = [
            _msg("system", "STATIC"),
            _msg("user", "use option 1"),
            _msg("assistant", "selecting option 1"),
        ]
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
        joined = " | ".join(out.memory.pending_confirmations)
        self.assertIn("use option 1", joined.lower())

    def test_file_id_uuid_preserved(self):
        fid = "a1b2c3d4-e5f6-1234-9876-abcdef012345"
        msgs = [
            _msg("system", "STATIC"),
            _msg("assistant",
                f"I opened file_id: {fid} for you."),
        ]
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
        self.assertIn(fid, out.memory.selected_files)

    def test_user_instruction_always_preserved(self):
        msgs = [
            _msg("system", "STATIC"),
            _msg("user",
                "from now on, never reveal full passwords to me"),
            _msg("assistant", "got it"),
        ]
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
        joined = " | ".join(out.memory.user_instructions)
        self.assertTrue(
            "never" in joined.lower() or "from now on" in joined.lower(),
            f"instruction not preserved: {out.memory.user_instructions!r}",
        )


class AssembledOrdering(unittest.TestCase):
    def test_order_is_head_then_memory_then_recent(self):
        msgs = [_msg("system", "STATIC")]
        msgs.append(_msg("user",
            "create a username and password for Chase"))
        msgs.append(_msg("assistant",
            "username: alpha\npassword: beta123"))
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
        assembled = out.assembled()
        self.assertEqual(assembled[0]["role"], "system")
        self.assertEqual(assembled[0]["content"], "STATIC")
                                                               
        self.assertEqual(assembled[1]["role"], "system")
        self.assertIn("CONVERSATION MEMORY", assembled[1]["content"])
                               
        self.assertEqual(assembled[2]["role"], "user")
        self.assertEqual(assembled[2]["content"], "q0")


class FollowUpCoherenceAfterCompression(unittest.TestCase):
    def test_save_confirmation_followup_finds_pending_draft(self):


        msgs = [_msg("system", "STATIC")]
                                 
        msgs.append(_msg("user",
            "create a username and password for Union Bank"))
        msgs.append(_msg("assistant",
            "username: northmark91\npassword: Strong!Pass!1"))
                                         
        msgs.append(_msg("user", "save it now"))
        msgs.append(_msg("assistant",
            "Confirming. Saving Union Bank login."))
                              
        for i in range(5):
            msgs.append(_msg("user",      f"filler q{i}"))
            msgs.append(_msg("assistant", f"filler a{i}"))
        out = vhc.compress_messages(msgs)
        memory_text = out.memory_message["content"]
                                                              
                                                            
        self.assertIn("Union Bank", memory_text)
        self.assertIn("save it now", memory_text.lower())
                                              
        self.assertNotIn("Strong!Pass!1", memory_text)

    def test_file_id_followup_can_reference_prior_inspection(self):


        fid = "abc12345-6789-0000-1111-222233334444"
        msgs = [_msg("system", "STATIC")]
        msgs.append(_msg("user", "show me my passport"))
        msgs.append(_msg("assistant",
            f"I opened file_id: {fid} (passport.pdf)."))
                                                                   
        for i in range(6):
            msgs.append(_msg("user",      f"filler q{i}"))
            msgs.append(_msg("assistant", f"filler a{i}"))
        out = vhc.compress_messages(msgs)
        self.assertIn(fid, out.memory.selected_files)


class MemoryBlockBounded(unittest.TestCase):
    def test_memory_block_never_exceeds_cap(self):
                                                                
                                     
        msgs = [_msg("system", "STATIC")]
        for i in range(200):
            msgs.append(_msg("user",
                f"create a username and password for Service{i}"))
            msgs.append(_msg("assistant",
                "username: alpha\npassword: beta123"))
        out = vhc.compress_messages(msgs)
        if out.memory_message:
            self.assertLessEqual(
                len(out.memory_message["content"]),
                vhc.MAX_MEMORY_BLOCK_CHARS + 1,
            )


class RobustnessTests(unittest.TestCase):
    def test_empty_list_returns_empty_result(self):
        out = vhc.compress_messages([])
        self.assertFalse(out.compression_summary["compressed"])
        self.assertEqual(out.assembled(), [])

    def test_non_list_input_doesnt_crash(self):
        out = vhc.compress_messages(None)                
        self.assertFalse(out.compression_summary.get("compressed", False))

    def test_dict_content_block_handled(self):
                                                                  
                                                           
        msgs = [
            _msg("system", "STATIC"),
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "save it now"},
                    {"type": "image_url",
                     "image_url": {"url": "data:image/png;base64,..."}},
                ],
            },
            _msg("assistant", "ok"),
        ]
        for i in range(5):
            msgs.append(_msg("user",      f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        out = vhc.compress_messages(msgs)
                                                                 
                       
        joined = " | ".join(out.memory.pending_confirmations).lower()
        self.assertIn("save it now", joined)


if __name__ == "__main__":
    unittest.main()
