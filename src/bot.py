"""
Real Estate Bot - Main Pipeline and Orchestration.
Clean, focused bot implementation with separated concerns.
"""

import asyncio
import traceback
from typing import Optional
from loguru import logger
from strands import Agent

from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frameworks.rtvi import (
    RTVIConfig,
    RTVIObserver,
    RTVIProcessor,
    RTVIObserverParams,
)
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport

from .config import settings
from .prompts import system_prompts, agent_prompts
from .tools import execute_hybrid_search


class RealEstateBot:
    """
    Real Estate Bot class with clean separation of concerns.
    Handles bot initialization, pipeline setup, and orchestration.
    """

    def __init__(self):
        """Initialize the bot with all necessary components."""
        self.task: Optional[PipelineTask] = None
        self.rtvi: Optional[RTVIProcessor] = None
        self.is_running = False
        self.strands_agent = None

        # Validate configuration
        settings.validate_required_keys()
        
        # Initialize Strands agent
        self._initialize_strands_agent()

    def _initialize_strands_agent(self):
        """Initialize the Strands agent with property search capabilities."""
        self.strands_agent = Agent(
            tools=[execute_hybrid_search],
            system_prompt=agent_prompts.PROPERTY_SEARCH_AGENT,
        )
        logger.info("✅ Strands agent initialized with property search tool")

    async def handle_property_search_queries(
        self,
        params: FunctionCallParams,
        query: str,
    ):
        """
        Handle property search queries using Strands agent.
        This is the main entry point for property searches.
        """
        logger.info(f"🔍 Handling property search query: '{query}'")

        try:
            # Get current event loop and RTVI instance
            loop = asyncio.get_event_loop()
            
            # Create a context-aware search tool
            def execute_search_with_context(*args, **kwargs):
                return execute_hybrid_search(
                    *args,
                    rtvi_instance=self.rtvi,
                    event_loop=loop,
                    **kwargs
                )
            
            # Temporarily replace the tool in Strands agent with context
            original_tool = None
            for i, tool_func in enumerate(self.strands_agent.tools):
                if tool_func.__name__ == 'execute_hybrid_search':
                    original_tool = tool_func
                    self.strands_agent.tools[i] = execute_search_with_context
                    break
            
            # Execute search and summarization via Strands agent
            result = await loop.run_in_executor(None, self.strands_agent, query)
            
            # Restore original tool
            if original_tool:
                for i, tool_func in enumerate(self.strands_agent.tools):
                    if tool_func == execute_search_with_context:
                        self.strands_agent.tools[i] = original_tool
                        break
            
            logger.info("✅ Property search completed successfully")

            # Return the conversational response to the LLM
            await params.result_callback(result.message)
            logger.info("🔊 Search results sent to TTS pipeline")

        except Exception as e:
            logger.error(f"❌ Error in property search handler: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")

            # Send user-friendly error response
            error_message = (
                "I encountered an issue while searching for properties. "
                "Please try rephrasing your request or try again in a moment."
            )
            await params.result_callback(error_message)

    def _create_services(self):
        """Create and configure all required services."""
        # Text-to-Speech Service
        tts = CartesiaTTSService(
            api_key=settings.CARTESIA_API_KEY,
            voice_id=settings.CARTESIA_VOICE_ID,
        )

        # Large Language Model Service
        llm = OpenAILLMService(api_key=settings.OPENAI_API_KEY)

        # Register property search function
        llm.register_direct_function(self.handle_property_search_queries)

        # Add function call started handler
        @llm.event_handler("on_function_calls_started")
        async def on_function_calls_started(service, function_calls):
            await tts.queue_frame(
                TTSSpeakFrame("Let me search for that property information.")
            )

        # Speech-to-Text Service
        stt = DeepgramSTTService(api_key=settings.DEEPGRAM_API_KEY)

        return tts, llm, stt

    def _create_context_and_tools(self, llm):
        """Create LLM context and tools configuration."""
        # Setup tools schema
        tools = ToolsSchema(standard_tools=[self.handle_property_search_queries])
        
        # Initial conversation messages
        messages = [
            {
                "role": "system",
                "content": system_prompts.MAIN_BOT_SYSTEM_PROMPT,
            },
        ]

        # Create context and aggregator
        context = OpenAILLMContext(messages, tools)
        context_aggregator = llm.create_context_aggregator(context)
        
        return context_aggregator

    def _create_transport(self, room_url: str, token: str):
        """Create and configure Daily transport."""
        transport = DailyTransport(
            room_url,
            token,
            "Real Estate Assistant",
            DailyParams(
                audio_out_enabled=True,
                audio_in_enabled=True,
                vad_analyzer=SileroVADAnalyzer(
                    params=VADParams(stop_secs=settings.VAD_STOP_SECONDS)
                ),
            ),
        )
        return transport

    def _create_rtvi_components(self, transport):
        """Create RTVI processor and observer."""
        # Create RTVI processor
        self.rtvi = RTVIProcessor(
            config=RTVIConfig(config=[]), 
            transport=transport
        )

        # Create RTVI observer
        rtvi_observer = RTVIObserver(
            self.rtvi,
            params=RTVIObserverParams(
                bot_llm_enabled=True,
                bot_tts_enabled=True,
                user_transcription_enabled=True,
                metrics_enabled=True,
                errors_enabled=True,
            ),
        )

        return rtvi_observer

    def _setup_event_handlers(self, transport, context_aggregator):
        """Setup event handlers for transport and RTVI."""
        
        @self.rtvi.event_handler("on_client_ready")
        async def on_client_ready(rtvi):
            await rtvi.set_bot_ready()
            await self.task.queue_frames(
                [context_aggregator.user().get_context_frame()]
            )

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, participant):
            try:
                await transport.capture_participant_transcription(participant["id"])
                participant_name = participant.get('info', {}).get('userName', 'Unknown')
                logger.info(f"✅ Client connected: {participant_name}")
            except Exception as e:
                logger.error(f"❌ Error in client connected handler: {e}")

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, participant):
            try:
                participant_name = participant.get('info', {}).get('userName', 'Unknown')
                logger.info(f"👋 Client disconnected: {participant_name}")
            except Exception as e:
                logger.error(f"❌ Error in client disconnected handler: {e}")

    async def start(self, room_url: str, token: str):
        """
        Start the real estate bot with the given room URL and token.
        Main orchestration method that sets up the entire pipeline.
        """
        logger.info("🚀 Starting Real Estate Search Bot...")

        try:
            # Set running state
            self.is_running = True

            # Create all services
            tts, llm, stt = self._create_services()
            logger.info("✅ Services created successfully")

            # Create context and tools
            context_aggregator = self._create_context_and_tools(llm)
            logger.info("✅ Context and tools configured")

            # Create transport
            transport = self._create_transport(room_url, token)
            logger.info("✅ Daily transport created")

            # Create RTVI components
            rtvi_observer = self._create_rtvi_components(transport)
            logger.info("✅ RTVI components created")

            # Setup event handlers
            self._setup_event_handlers(transport, context_aggregator)
            logger.info("✅ Event handlers configured")

            # Build the pipeline
            pipeline = Pipeline([
                transport.input(),
                stt,
                self.rtvi,
                context_aggregator.user(),
                llm,
                tts,
                transport.output(),
                context_aggregator.assistant(),
            ])
            logger.info("✅ Pipeline constructed")

            # Create and configure the pipeline task
            self.task = PipelineTask(
                pipeline,
                params=PipelineParams(
                    enable_metrics=True,
                    enable_usage_metrics=True,
                ),
                observers=[rtvi_observer],
            )
            logger.info("✅ Pipeline task created with observers")

            # Run the pipeline
            runner = PipelineRunner()
            logger.info("🎯 Starting pipeline execution...")
            await runner.run(self.task)

        except Exception as e:
            logger.error(f"❌ Bot startup error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

        finally:
            self.is_running = False
            logger.info("🛑 Bot execution completed")


async def run_bot(room_url: str, token: str):
    """
    Main entry point for running the real estate bot.
    Creates and starts a new bot instance.
    """
    logger.info(f"🎬 Initializing Real Estate Bot for room: {room_url}")
    
    bot = RealEstateBot()
    try:
        await bot.start(room_url, token)
    except Exception as e:
        logger.error(f"❌ Fatal bot error: {e}")
        raise
