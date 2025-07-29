#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Configuration settings for the real estate bot."""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

# Database
MONGODB_CONNECTION_STRING = "mongodb+srv://allengeorgemylath:Mylath%4090@cluster0.jy2twdh.mongodb.net/real_estate"

# Voice Settings
CARTESIA_VOICE_ID = "71a7ad14-091c-4e8e-a314-022ece01c121"  # British Reading Lady

# Search Settings
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_VECTOR_INDEX = "vector_index"
SEARCH_TIMEOUT_SECONDS = 30

# VAD Settings
VAD_STOP_SECONDS = 0.5

# RTVI Settings
RTVI_MESSAGE_TIMEOUT = 5.0
RTVI_ERROR_TIMEOUT = 3.0
