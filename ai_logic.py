import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import requests
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False

def _load_local_env_file():
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_dotenv()
_load_local_env_file()


class HandshakeLiveEngine:
    def __init__(self, provider_timeout=4.0):
        self.provider_timeout = provider_timeout
        self.http_timeout = (3.0, provider_timeout)
        self.providers = [
            ("gemini_1_5_flash", self._call_gemini),
            ("openrouter", self._call_openrouter),
            ("openai", self._call_openai),
            ("mistral_free", self._call_mistral),
            ("groq_llama_3_1", self._call_groq),
            ("together_free", self._call_together),
            ("huggingface_inference", self._call_huggingface),
        ]

    def generate_live_expert_result(self, item_query, user_request=None):
        clean_query = self._clean_subject(item_query)
        live_provider_available = self.has_live_provider_credentials()
        for _provider_name, provider in self.providers:
            payload = self._run_provider_with_timeout(provider, clean_query, user_request)
            if payload:
                payload["live_provider_available"] = live_provider_available
                return payload
        result = self._build_local_fallback(clean_query, user_request)
        result["live_provider_available"] = live_provider_available
        return result

    def generate_live_expert_data(self, item_query, user_request=None):
        result = self.generate_live_expert_result(item_query, user_request)
        return result["payload"]

    def has_live_provider_credentials(self):
        return any([
            self._get_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            self._get_api_key("GROQ_API_KEY"),
            self._get_api_key("MISTRAL_API_KEY"),
            self._get_api_key("OPENROUTER_API_KEY"),
            self._get_api_key("OPENAI_API_KEY"),
            self._get_api_key("TOGETHER_API_KEY"),
            self._get_api_key("HUGGINGFACE_API_KEY", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN"),
        ])

    def _run_provider_with_timeout(self, provider, item_query, user_request):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(provider, item_query, user_request)
            try:
                return future.result(timeout=self.provider_timeout)
            except FuturesTimeoutError:
                future.cancel()
                return None
            except Exception:
                return None

    def _clean_subject(self, item_query):
        subject = " ".join((item_query or "").split()).strip(" .,-")
        for noise in (" professional", " hobbies", " tools", " books", " cars", " tech", " houses"):
            if subject.lower().endswith(noise):
                subject = subject[: -len(noise)].strip(" .,-")
        return subject or "this item"

    def _prompt(self, item_query, user_request=None):
        request_text = (user_request or "").strip()
        request_line = f"User request: {user_request}. " if user_request else ""
        if request_text.lower() in {"hi", "hello", "hey", "yo"}:
            return (
                "You are HandShake AI. Return only strict JSON with keys "
                "teaching_guide, mentor_tip, visual_effect, brand_color. "
                "For greetings, teaching_guide should be 3 short friendly chat lines that greet the user and ask what item help they need. "
                "mentor_tip should be one short friendly sentence. "
                f"Item query: {item_query}"
            )
        return (
            "You are HandShake Live Expert. Return only strict JSON with keys "
            "teaching_guide, mentor_tip, visual_effect, brand_color. "
            "Make the answer specific to the exact item, not generic. "
            "teaching_guide must be an array of exactly 3 short strings. "
            "mentor_tip must be one sentence. "
            f"{request_line}Item query: {item_query}"
        )

    def _extract_json(self, raw_text, item_query):
        if not raw_text:
            return None

        text = raw_text.strip()
        if "```" in text:
            chunks = [chunk.strip() for chunk in text.split("```") if chunk.strip()]
            for chunk in chunks:
                if chunk.startswith("json"):
                    text = chunk[4:].strip()
                    break

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        try:
            payload = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
        return self._normalize_payload(payload, item_query)

    def _normalize_payload(self, payload, item_query):
        if not isinstance(payload, dict):
            return None

        guide = payload.get("teaching_guide")
        mentor_tip = payload.get("mentor_tip")
        visual_effect, brand_color = self._effect_and_color(item_query)

        if not isinstance(guide, list):
            return None
        steps = [str(step).strip() for step in guide if str(step).strip()]
        if len(steps) < 3:
            return None
        if not mentor_tip or not str(mentor_tip).strip():
            return None

        return {
            "teaching_guide": steps[:3],
            "mentor_tip": str(mentor_tip).strip(),
            "visual_effect": visual_effect,
            "brand_color": payload.get("brand_color") or brand_color,
        }

    def _headers(self, api_key):
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _get_api_key(self, *names):
        for name in names:
            value = os.getenv(name)
            if value:
                return value
        return None

    def _call_gemini(self, item_query, user_request=None):
        api_key = self._get_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
        if not api_key:
            return None

        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [
                    {
                        "parts": [
                            {
                                "text": self._prompt(item_query, user_request)
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.35,
                    "maxOutputTokens": 240,
                    "responseMimeType": "application/json",
                },
            },
            timeout=self.http_timeout,
        )
        response.raise_for_status()
        body = response.json()
        text = ""
        candidates = body.get("candidates") or []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                text = parts[0].get("text", "") or ""
        payload = self._extract_json(text, item_query)
        if payload:
            return {"payload": payload, "source": "gemini"}
        return None

    def _call_groq(self, item_query, user_request=None):
        api_key = self._get_api_key("GROQ_API_KEY")
        if not api_key:
            return None

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=self._headers(api_key),
            json={
                "model": "llama-3.1-8b-instant",
                "temperature": 0.35,
                "max_tokens": 240,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only. Make it item-specific."},
                    {"role": "user", "content": self._prompt(item_query, user_request)},
                ],
            },
            timeout=self.http_timeout,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        payload = self._extract_json(text, item_query)
        if payload:
            return {"payload": payload, "source": "groq"}
        return None

    def _call_mistral(self, item_query, user_request=None):
        api_key = self._get_api_key("MISTRAL_API_KEY")
        if not api_key:
            return None

        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers=self._headers(api_key),
            json={
                "model": "mistral-small-latest",
                "temperature": 0.35,
                "max_tokens": 240,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only. Make it item-specific."},
                    {"role": "user", "content": self._prompt(item_query, user_request)},
                ],
            },
            timeout=self.http_timeout,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        payload = self._extract_json(text, item_query)
        if payload:
            return {"payload": payload, "source": "mistral"}
        return None

    def _call_together(self, item_query, user_request=None):
        api_key = self._get_api_key("TOGETHER_API_KEY")
        if not api_key:
            return None

        response = requests.post(
            "https://api.together.xyz/v1/chat/completions",
            headers=self._headers(api_key),
            json={
                "model": "meta-llama/Llama-3.2-3B-Instruct-Turbo",
                "temperature": 0.35,
                "max_tokens": 240,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only. Make it item-specific."},
                    {"role": "user", "content": self._prompt(item_query, user_request)},
                ],
            },
            timeout=self.http_timeout,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        payload = self._extract_json(text, item_query)
        if payload:
            return {"payload": payload, "source": "together"}
        return None

    def _call_openrouter(self, item_query, user_request=None):
        api_key = self._get_api_key("OPENROUTER_API_KEY")
        if not api_key:
            return None

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                **self._headers(api_key),
                "HTTP-Referer": "http://localhost",
                "X-Title": "HandShake",
            },
            json={
                "model": "openai/gpt-4o-mini",
                "temperature": 0.35,
                "max_tokens": 240,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only. Make it item-specific."},
                    {"role": "user", "content": self._prompt(item_query, user_request)},
                ],
            },
            timeout=self.http_timeout,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        payload = self._extract_json(text, item_query)
        if payload:
            return {"payload": payload, "source": "openrouter"}
        return None

    def _call_openai(self, item_query, user_request=None):
        api_key = self._get_api_key("OPENAI_API_KEY")
        if not api_key:
            return None

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=self._headers(api_key),
            json={
                "model": "gpt-4o-mini",
                "temperature": 0.35,
                "max_tokens": 240,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only. Make it item-specific."},
                    {"role": "user", "content": self._prompt(item_query, user_request)},
                ],
            },
            timeout=self.http_timeout,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        payload = self._extract_json(text, item_query)
        if payload:
            return {"payload": payload, "source": "openai"}
        return None

    def _call_huggingface(self, item_query, user_request=None):
        api_key = self._get_api_key("HUGGINGFACE_API_KEY", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN")
        if not api_key:
            return None

        response = requests.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers=self._headers(api_key),
            json={
                "model": "mistralai/Mistral-7B-Instruct-v0.3",
                "temperature": 0.35,
                "max_tokens": 240,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only. Make it item-specific."},
                    {"role": "user", "content": self._prompt(item_query, user_request)},
                ],
            },
            timeout=self.http_timeout,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        payload = self._extract_json(text, item_query)
        if payload:
            return {"payload": payload, "source": "huggingface"}
        return None

    def _effect_and_color(self, item_query):
        query = (item_query or "").lower()
        if "piano" in query or "guitar" in query:
            return "music_notes", "#ffd700"
        if any(token in query for token in ("electronics", "laptop", "camera", "phone", "drone", "console", "canon", "sony")):
            return "cyber_grid", "#00f5ff"
        if any(token in query for token in ("tool", "drill", "kit", "hammer", "saw", "wrench", "bosch")):
            return "sparks", "#ffd700"
        return "cyber_grid", "#14b8a6"

    def _infer_item_family(self, item_query):
        query = (item_query or "").lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", query)
        words = set(normalized.split())

        def has_word(*tokens):
            return any(token in words for token in tokens)

        def has_phrase(phrase):
            return phrase in normalized

        if has_word("canon", "sony", "nikon", "camera", "eos", "lens", "mirrorless"):
            return "camera"
        if has_word("drill", "toolkit", "tool", "wrench", "saw", "bosch", "hammer"):
            return "tools"
        if has_word("guitar", "piano", "keyboard", "violin", "music"):
            return "music"
        if has_word("playstation", "ps5", "xbox", "controller", "console"):
            return "console"
        if has_word("car", "bmw", "toyota", "mercedes", "camry", "x5", "vehicle") or has_phrase("g class"):
            return "car"
        if has_word("drone", "mavic"):
            return "drone"
        if has_word("bike", "bicycle", "skateboard"):
            return "mobility"
        return "generic"

    def _family_guidance(self, family, subject, user_request):
        request = (user_request or "").lower()
        setup_request = any(token in request for token in ("set up", "setup", "install", "connect", "assemble"))

        if family == "camera":
            if setup_request:
                return [
                    f"Step 1: Charge the battery for {subject}, insert a fast SD or CFexpress card, and mount the lens until it clicks.",
                    f"Step 2: Reset the camera menu, set photo mode, confirm autofocus, and choose a safe default like JPEG plus Auto ISO.",
                    f"Step 3: Take a test burst, review focus sharpness and card write speed, then clean the sensor-side lens caps before storage.",
                ], f"Pro tip: on {subject}, test both card slots and every battery before rental day, because storage or power failure is the fastest way to lose trust."

            return [
                f"Step 1: Inspect the lens mount, rear screen, hot shoe, and battery door on {subject} for impact wear or bent contacts.",
                f"Step 2: Check autofocus speed, shutter response, dial control, and card-slot detection with an actual lens attached.",
                f"Step 3: Shoot one indoor and one outdoor sample, then zoom into the files to verify sharp focus and no sensor dust streaks.",
            ], f"Pro tip: for {subject}, always inspect the image corners at 100 percent because soft corners often expose a bad lens or misfocus faster than the center does."

        if family == "tools":
            if setup_request:
                return [
                    f"Step 1: Match the correct bit, blade, or attachment to {subject} and lock it fully before powering on.",
                    f"Step 2: Verify the voltage source or battery pack, then run the tool unloaded for a few seconds to check vibration and sound.",
                    f"Step 3: Test {subject} on scrap material first so speed, torque, and safety guards are confirmed before real work starts.",
                ], f"Pro tip: with {subject}, a five-second no-load test reveals bearing noise early and saves you from lending out a failing tool."

            return [
                f"Step 1: Check the chuck, trigger, battery contacts, guard, and any quick-release points on {subject} for looseness.",
                f"Step 2: Confirm the motor starts smoothly with no burning smell, grinding noise, or inconsistent speed.",
                f"Step 3: Test the tool under light pressure on scrap material and verify it stays straight without overheating.",
            ], f"Pro tip: if {subject} twists under light load, the problem is often a worn bit lock or loose chuck, not operator error."

        if family == "music":
            if setup_request:
                return [
                    f"Step 1: Position {subject} on a stable stand or surface and confirm power, pedals, strap, or tuning accessories are ready.",
                    f"Step 2: Tune or calibrate {subject} before use and test volume at low level first to catch cable or pickup problems cleanly.",
                    f"Step 3: Play a full scale and a few dynamic passages so dead notes, fret buzz, or uneven key response show up immediately.",
                ], f"Pro tip: the fastest way to judge {subject} is one slow scale across the full range, because weak notes appear before style does."

            return [
                f"Step 1: Inspect strings, keys, pedals, jacks, and tuning stability on {subject} before the first practice run.",
                f"Step 2: Check tone consistency across the full range instead of only the most comfortable notes.",
                f"Step 3: Test sustain, dynamics, and any amplification path so the instrument behaves the same after 10 minutes as it did at minute one.",
            ], f"Pro tip: when {subject} sounds fine at first but drifts later, temperature and cable tension are usually the real issue."

        if family == "console":
            if setup_request:
                return [
                    f"Step 1: Connect {subject} to power, HDMI, and network, then confirm the controller pairs and charges correctly.",
                    f"Step 2: Update system software, check storage space, and launch one installed game to verify loading speed.",
                    f"Step 3: Test every controller button, both sticks, and the cooling noise level before regular play begins.",
                ], f"Pro tip: with {subject}, the fastest trust check is opening a game and leaving it running for ten minutes to expose heat or fan issues."

            return [
                f"Step 1: Inspect the HDMI port, USB ports, controller charging cable, and fan vents on {subject}.",
                f"Step 2: Confirm it boots without display flicker, controller drift, or random disconnects.",
                f"Step 3: Run a game long enough to check thermals, loading stability, and controller response under real input.",
            ], f"Pro tip: controller drift often appears only in menus with slow cursor movement, so test there before you trust the stick."

        if family == "car":
            if setup_request:
                return [
                    f"Step 1: Walk around {subject}, record existing body marks, and confirm fuel, tire pressure, and documents are ready.",
                    f"Step 2: Adjust mirrors and seat, test lights and brakes, then verify the dash shows no warning lights.",
                    f"Step 3: Drive a short mixed route to confirm steering, acceleration, braking, and reverse camera behavior.",
                ], f"Pro tip: with {subject}, a 60-second dashboard video at handoff prevents more disputes than any written checklist."

            return [
                f"Step 1: Inspect the tires, lights, mirrors, windshield, and lower bumper edges on {subject} before driving.",
                f"Step 2: Start the engine and watch for warning lights, rough idle, delayed shifting, or unusual vibration.",
                f"Step 3: Test the brakes, steering center, and parking sensors on a short local route before committing.",
            ], f"Pro tip: a slight pull under braking on {subject} usually appears before the renter notices it, so catch it during the first low-speed stop."

        if family == "drone":
            if setup_request:
                return [
                    f"Step 1: Charge every flight battery for {subject}, unfold the frame, and inspect props for chips or looseness.",
                    f"Step 2: Link the controller, confirm GPS lock, and calibrate compass or gimbal only if the app actually asks for it.",
                    f"Step 3: Hover low for the first minute and test return-to-home before flying distance shots.",
                ], f"Pro tip: with {subject}, a stable 30-second hover tells you more about readiness than any menu screen does."

            return [
                f"Step 1: Check propellers, battery latches, gimbal movement, and landing feet on {subject}.",
                f"Step 2: Verify controller link, camera feed, and GPS count before lift-off.",
                f"Step 3: Perform a short hover and slow yaw test to catch drift, vibration, or gimbal shake early.",
            ], f"Pro tip: tiny prop damage on {subject} often shows up first as micro-jello in video, not as obvious flight instability."

        if family == "mobility":
            return [
                f"Step 1: Inspect brakes, tire pressure, deck or frame tightness, and battery or chain condition on {subject}.",
                f"Step 2: Set the rider stance and controls first, then test low-speed response before a full ride.",
                f"Step 3: Do one short loop and recheck bolts, braking feel, and wheel alignment after the first few minutes.",
            ], f"Pro tip: if {subject} feels fine when stationary but unstable on rollout, check front alignment before blaming the rider."

        return [
            f"Step 1: Inspect the main body, accessories, and power or moving parts on {subject} for wear or missing pieces.",
            f"Step 2: Set up {subject} in the intended order and confirm the core controls respond correctly.",
            f"Step 3: Run one realistic test so the item proves itself before you trust it in front of the next user.",
        ], f"Pro tip: the quickest way to judge {subject} is a short real-use test, because hidden faults rarely show up during a static inspection."

    def _build_local_fallback(self, item_query, user_request=None):
        subject = self._clean_subject(item_query)
        request = (user_request or "").strip().lower()
        if request in {"hi", "hello", "hey", "yo"}:
            return {
                "payload": {
                    "teaching_guide": [
                        "Hi, I can help you learn an item or walk through setup.",
                        "Tell me what item you have or what part is confusing.",
                        "If you want, ask me for setup steps, safety checks, or beginner tips.",
                    ],
                    "mentor_tip": "The clearer your item name and problem, the better the answer will be.",
                    "visual_effect": "cyber_grid",
                    "brand_color": "#14b8a6",
                },
                "source": "fallback",
            }
        family = self._infer_item_family(subject)
        steps, mentor_tip = self._family_guidance(family, subject, user_request)
        visual_effect, brand_color = self._effect_and_color(subject)
        return {
            "payload": {
                "teaching_guide": steps,
                "mentor_tip": mentor_tip,
                "visual_effect": visual_effect,
                "brand_color": brand_color,
            },
            "source": "fallback",
        }
