# Hard-case results (generated from the batch runner)

Footage here is the built-in mock provider, so these results show the *engine's decisions* (queries, flags, failures), not the quality of real stock footage. Relevance scores with the mock provider are inflated by construction and must not be quoted as measured relevance.

| Input | Result | What the engine did |
|---|---|---|
| 01_abstract.txt | succeeded, QA passed | queries: “hands shaking close up”; “beats talent talent work” |
| 02_statistics.txt | succeeded, QA passed | queries: “sales business growth chart graph”; “revenue crossed business growth chart graph” |
| 03_named_person_brand.txt | succeeded, QA passed | queries: “double production year” [NAMED_ENTITY_GENERIC_FOOTAGE]; “investors watching closely” · warnings: NAMED_ENTITY_GENERIC_FOOTAGE |
| 04a_bank_finance.txt | succeeded, QA passed | queries: “bank building exterior finance” |
| 04b_bank_river.txt | succeeded, QA passed | queries: “river bank nature water” |
| 04c_cloud_computing.txt | succeeded, QA passed | queries: “data center server room” |
| 04d_cloud_weather.txt | succeeded, QA passed | queries: “clouds in blue sky” |
| 04e_mouse_computer.txt | succeeded, QA passed | queries: “computer mouse on desk” |
| 04f_mouse_animal.txt | succeeded, QA passed | queries: “small mouse animal” |
| 04g_python_code.txt | succeeded, QA passed | queries: “programming code on laptop screen” |
| 04h_python_snake.txt | succeeded, QA passed | queries: “python snake wildlife” |
| 04i_value_business.txt | succeeded, QA passed | queries: “team collaboration office meeting” |
| 05_sad_news.txt | succeeded, QA passed | queries: “candle flame dark” [SENSITIVE_TOPIC_RESPECTFUL_FOOTAGE, AVOID_PEOPLE_BEST_EFFORT]; “rain on window” [SENSITIVE_TOPIC_RESPECTFUL_FOOTAGE, AVOID_PEOPLE_BEST_EFFORT] · warnings: SENSITIVE_TOPIC_RESPECTFUL_FOOTAGE |
| 06_tutorial.txt | succeeded, QA passed | queries: “start opening settings menu”; “choose privacy tab switch”; “save done” |
| 07_portrait_edge_9x16.json | succeeded, QA passed | queries: “tall cyclist rides along”; “scene stays calm bright” |
| 08_scene_list_with_hints.json | succeeded, QA passed | queries: “creator editing video”; “stopwatch” |
| 09_empty_script.json | rejected (400) `EMPTY_INPUT` | refused up front with a JSON error |
| 10_hindi_voice.json | succeeded, QA passed | queries: “abstract light background”; “abstract light background” |
| 11_wrong_file_type.pdf | rejected (415) `UNSUPPORTED_MEDIA_TYPE` | refused up front with a JSON error |
| 12_voiceover.mp3 | succeeded, QA passed | queries: “saving money starts small”; “put little aside month” |
| 13_silent.wav | failed `SILENT_AUDIO` | job failed with a clear, non-retryable error instead of a bad video |
| 14_music_only.mp3 | failed `NO_SPEECH_DETECTED` | job failed with a clear, non-retryable error instead of a bad video |
| 15_corrupt.mp3 | failed `UNSUPPORTED_MEDIA_TYPE` | job failed with a clear, non-retryable error instead of a bad video |
