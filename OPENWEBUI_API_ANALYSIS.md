# OpenWebUI API Comprehensive Analysis

**Research Date:** February 17, 2026  
**Source:** open-webui/open-webui repository  
**Current Integration:** Simple `requests.post()` with `{"messages": [{"role": "...", "content": "..."}]}` format

---

## Executive Summary

OpenWebUI provides a **rich, production-ready API** far beyond basic chat completions. The current MeshCore integration uses only a minimal subset of available capabilities. This document identifies **advanced features that could significantly enhance the chatbot experience**, including streaming, RAG/knowledge bases, function calling, tool integration, and real-time capabilities.

---

## 1. AVAILABLE REST API ENDPOINTS

### 1.1 Core Chat & Completion APIs

#### **POST `/api/v1/chat/completions`** (Primary or `/api/chat/completions`)
- **Status:** ✅ Core production endpoint
- **Authentication:** Bearer token required
- **Current Usage:** Your system uses this
- **Features:**
  - Streaming support via `"stream": true`
  - Multiple models per request
  - metadata tracking (timestamps, user info, session data)
  - Tool/function calling support
  - System prompt bypass control
  - Direct model access for testing

#### **POST `/api/chat/completed`** (Webhook-like endpoint)
- **Status:** ✅ Available
- **Purpose:** Signal when chat completion is done (for tracking, analytics, cleanup)
- **Payload:** Form data with model_item, background tasks tracking

#### **POST `/api/v1/embeddings`** (also `/api/embeddings`)
- **Status:** ✅ Production ready
- **Purpose:** Generate embeddings for RAG/vector search
- **Supports:** OpenAI-compatible format
- **Backends:** Ollama, OpenAI, Azure OpenAI, SentenceTransformers (default)

### 1.2 Model Management Endpoints

#### **GET `/api/v1/models`** (also `/api/models`)
- **Status:** ✅ Production
- **Returns:** List of available models with full metadata
- **Includes:** Model info, capabilities, configuration, ownership
- **Parameters:**
  - `refresh=true` - Force refresh from backend
  - Filters based on user role/permissions

#### **GET `/api/v1/models/base`**
- Status: ✅ Available
- Returns: Base models only (unfiltered)

#### **GET `/api/v1/models/model?id=<model_id>`**
- Returns detailed metadata for specific model

#### **GET `/api/v1/models/{id}/profile/image`**
- Returns model profile image/logo

### 1.3 Chat History & Management

#### **GET `/api/v1/chats/`** or **`/api/v1/chats/list`**
- **Status:** ✅ Production
- **Parameters:**
  - `page`: Pagination
  - `include_pinned`: Include pinned chats
  - `include_folders`: Include folder references
- **Returns:** `ChatTitleIdResponse[]`

#### **GET `/api/v1/chats/{id}`**
- Retrieve complete chat history
- Response: `ChatResponse` with full messages and metadata

#### **POST `/api/v1/chats/new`**
- Create new chat with initial data

#### **POST `/api/v1/chats/{id}`**
- Update chat (title, messages, metadata)

#### **DELETE `/api/v1/chats/{id}`**
- Delete single chat

#### **DELETE `/api/v1/chats/`**
- Delete all user chats

#### **GET `/api/v1/chats/all`**
- Get all chats for user
- Available: `/all/archived`, `/all/tags`, `/all/db` (admin only)

#### **GET `/api/v1/chats/stats/usage`**
- Chat usage statistics per user

#### **GET `/api/v1/chats/stats/export`**
- Export all chat statistics (streaming JSONL format)
- Parameters: `updated_at`, `page`, `stream`

### 1.4 Knowledge Base / RAG Endpoints

#### **Core Knowledge Endpoints**
- **GET `/api/v1/knowledge/`** - List knowledge bases (paginated)
- **POST `/api/v1/knowledge/create`** - Create new knowledge base
- **GET `/api/v1/knowledge/{id}`** - Get specific knowledge base
- **POST `/api/v1/knowledge/{id}`** - Update knowledge base
- **DELETE `/api/v1/knowledge/{id}`** - Delete knowledge base

#### **Knowledge File Management**
- **POST `/api/v1/knowledge/{id}/file/add`** - Add file to knowledge base
- **POST `/api/v1/knowledge/{id}/file/remove`** - Remove file from knowledge base
- **POST `/api/v1/knowledge/{id}/file/update`** - Update file in knowledge base
- **GET `/api/v1/knowledge/{id}/files`** - Search files in knowledge base
- **POST `/api/v1/knowledge/reindex`** - Reindex all knowledge base documents

#### **Access Control**
- **GET `/api/v1/knowledge/{id}/access`** - Check access grants
- **POST `/api/v1/knowledge/{id}/access`** - Update access grants

### 1.5 Retrieval/RAG Configuration

#### **GET `/api/v1/retrieval/config`**
- Full RAG configuration including:
  - Vector database choice (9 options)
  - Embedding engine config
  - Reranking settings
  - Document extraction settings
  - Web search settings

#### **POST `/api/v1/retrieval/config/update`**
- Update RAG settings (admin only)

#### **POST `/api/v1/retrieval/process/text`**
- Process text directly into vector DB
- Creates collection from raw text

#### **POST `/api/v1/retrieval/process/file`**
- Process file (PDF, DOCX, etc.) into vector DB
- Supports multiple extraction engines

#### **POST `/api/v1/retrieval/process/files/batch`**
- Batch process multiple files

#### **POST `/api/v1/retrieval/query/doc`**
- Query documents with RAG
- Supports hybrid search (BM25 + vector)
- Can use reranking

### 1.6 File Upload & Management

#### **POST `/api/v1/files/`**
- **Status:** ✅ Production
- **Access:** Requires file_upload permission
- **Parameters:**
  - `process=true` - Automatically extract content
  - `process_in_background=true` - Async processing
  - `metadata` - File metadata (knowledge_id, etc.)
- **Returns:** `FileModelResponse` with processing status

#### **GET `/api/v1/files/{id}`**
- Retrieve file metadata

#### **GET `/api/v1/files/{id}/data/content`**
- Get extracted file content (text)

#### **POST `/api/v1/files/{id}/data/content/update`**
- Update extracted file content

#### **DELETE `/api/v1/files/{id}`**
- Delete file

#### **GET `/api/v1/files/{id}/process/status`**
- Get file processing status (streaming)

### 1.7 Authentication & User Management

#### **GET `/api/v1/auth/`** or **`/api/v1/auths/`**
- Login/session management

#### **POST `/oauth/{provider}/login/callback`**
- OAuth integration endpoints

#### **GET `/api/v1/users/profile`**
- User profile information

#### **POST `/api/v1/users/`**
- Create user (admin)

### 1.8 Analytics & Usage Tracking

#### **GET `/api/v1/analytics/models`**
- Model usage analytics (time-based filtering)

#### **GET `/api/v1/analytics/users`**
- Per-user analytics

#### **GET `/api/v1/analytics/tokens`**
- Token usage by model (input/output/total)

#### **GET `/api/v1/analytics/messages`**
- Message-level analytics with filters

#### **GET `/api/v1/analytics/models/{model_id}/chats`**
- All chats that used specific model (with preview)

### 1.9 Task & Background Job Management

#### **GET `/api/v1/tasks`**
- List active tasks

#### **GET `/api/v1/tasks/chat/{chat_id}`**
- Tasks for specific chat by ID

#### **POST `/api/v1/tasks/stop/{task_id}`**
- Stop running task

#### **POST `/api/v1/tasks/title/completions`**
- Generate chat title (background task)

#### **POST `/api/v1/tasks/queries/completions`**
- Generate search queries for RAG

#### **POST `/api/v1/tasks/auto/completions`**
- Auto-completion generation (search, general, etc.)

### 1.10 Tool Server / Function Calling

#### **Tool Configuration**
- **GET `/api/v1/tools/`** - List tool servers
- **POST `/api/v1/tools/`** - Add tool server (OpenAPI/MCP)
- **GET `/api/v1/tools/{id}`** - Get tool server details
- **POST `/api/v1/tools/{id}`** - Update tool server
- **DELETE `/api/v1/tools/{id}`** - Delete tool server

#### **Tool Execution**
- Tools are invoked via native function calling in chat
- Support for OpenAPI specifications
- MCP (Model Context Protocol) integration

### 1.11 Audio/Voice Endpoints

#### **GET `/api/v1/audio/models`**
- Available STT/TTS models

#### **GET `/api/v1/audio/voices`**
- Available voices for TTS

#### **POST `/api/v1/audio/transcription`**
- Speech-to-text

#### **POST `/api/v1/audio/speech`**
- Text-to-speech

### 1.12 Image Generation

#### **POST `/api/v1/images/`**
- Generate images from prompts

#### **GET `/api/v1/images/models`**
- Available image generation models

### 1.13 Configuration Endpoints

#### **GET `/api/config`**
- Global app configuration

#### **GET `/api/webhook`** / **POST `/api/webhook`**
- Webhook configuration for integrations

#### **GET `/api/version`**
- Application version info

#### **GET `/api/version/updates`**
- Check for available updates

---

## 2. CHAT COMPLETION PARAMETERS & RESPONSE FORMATS

### 2.1 Full Request Format

```json
{
  "model": "model-id",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant"
    },
    {
      "role": "user",
      "content": "Hello!"
    }
  ],
  "stream": true,
  "max_tokens": 2048,
  "temperature": 0.7,
  "top_p": 1.0,
  "frequency_penalty": 0,
  "presence_penalty": 0,
  
  // Advanced features
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "search_web",
        "description": "Search the web",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {"type": "string"}
          },
          "required": ["query"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  
  // RAG/Knowledge
  "documents": ["doc1", "doc2"],  // Document IDs
  "knowledge_ids": ["kb1"],  // Knowledge base IDs
  
  // Metadata & Control
  "metadata": {
    "chat_id": "chat-xxx",
    "user_id": "user-xxx",
    "session_id": "session-xxx",
    "message_id": "msg-xxx"  // For continuing messages
  },
  
  "params": {
    "stream_delta_chunk_size": 3,
    "reasoning_tags": ["<think>", "</think>"],
    "function_calling": "native"  // or "default"
  },
  
  // Stop sequences
  "stop": ["Human:", "Assistant:"],
  
  // Files for chat context
  "files": [
    {
      "id": "file-xxx",
      "name": "document.pdf",
      "type": "document"
    }
  ]
}
```

### 2.2 Non-Streaming Response Format

```json
{
  "id": "chatcmpl-xxx",
  "object": "text_completion",
  "created": 1708113600,
  "model": "gpt-4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Response text here"
      },
      "finish_reason": "stop"  // "stop", "tool_calls", "length", "error"
    }
  ],
  "usage": {
    "prompt_tokens": 50,
    "completion_tokens": 100,
    "total_tokens": 150
  },
  
  // Extended fields
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "status": "completed",
      "content": [
        {
          "type": "output_text",
          "text": "Response text here"
        }
      ],
      "id": "msg-xxx"
    }
  ],
  
  "sources": [
    {
      "document": "doc1",
      "source": "source1.pdf",
      "content": "Retrieved context"
    }
  ]
}
```

### 2.3 Streaming Response Format

**Format:** Server-Sent Events (SSE) with `text/event-stream`

```
data: {"choices":[{"delta":{"content":"Hello"}}]}

data: {"choices":[{"delta":{"content":" world"}}]}

data: {"choices":[{"finish_reason":"stop"}]}

data: [DONE]
```

**Extended Streaming with tool calls:**
```json
{
  "choices": [{
    "delta": {
      "tool_calls": [{
        "id": "call-xxx",
        "function": {
          "name": "search_web",
          "arguments": "{\"query\": \"OpenWebUI API\"}"
        }
      }]
    },
    "finish_reason": null
  }],
  "output": [
    {
      "type": "function_call",
      "id": "fc-xxx",
      "name": "search_web",
      "arguments": "{...}",
      "status": "in_progress"
    }
  ]
}
```

### 2.4 Output Format (OpenWebUI OR-Aligned)

OpenWebUI supports an **output-required (OR) aligned response format** for advanced features:

```json
{
  "output": [
    {
      "type": "message",
      "id": "msg-xxx",
      "role": "assistant",
      "status": "completed",
      "content": [
        {
          "type": "output_text",
          "text": "Main response"
        }
      ]
    },
    {
      "type": "reasoning",
      "id": "r-xxx",
      "status": "completed",
      "content": [{"type": "output_text", "text": "Internal reasoning"}],
      "summary": "Thought process"
    },
    {
      "type": "function_call",
      "id": "fc-xxx",
      "name": "search_web",
      "arguments": "{}",
      "status": "completed"
    },
    {
      "type": "function_call_output",
      "status": "completed",
      "output": [{"type": "input_text", "text": "Search results..."}]
    },
    {
      "type": "code_interpreter",
      "id": "ci-xxx",
      "code": "print('hello')",
      "output": "hello",
      "status": "completed"
    }
  ]
}
```

---

## 3. STREAMING CAPABILITIES & EVENT TYPES

### 3.1 Stream Types

✅ **SSE (Server-Sent Events)** - Primary method
- Content-Type: `text/event-stream`
- Format: `data: {json}\n\n`
- Works with all modern browsers and clients

✅ **NDJSON** - Alternative format
- Content-Type: `application/x-ndjson`
- Format: One JSON object per line

### 3.2 Streaming Events

| Event Type | Purpose | Example |
|-----------|---------|---------|
| `delta` | Token-by-token content | `{"delta": {"content": "word"}}` |
| `tool_calls` | Function call definitions | Streaming tool arguments |
| `output` | Real-time output items | Extended format with reasoning/tools |
| `sources` | Citation sources from RAG | Document references |
| `usage` | Token counts | At stream end |
| `error` | Streaming errors | Error messages and details |

### 3.3 Special Streaming Features

**Reasoning Tags Detection:**
- Auto-detect `<think>...</think>` or custom tags
- Separate reasoning from output
- Create reasoning output items

**Code Interpreter Detection:**
- Auto-detect `<code>...</code>` blocks
- Execute in sandbox
- Include execution output

**Solution/Artifact Tags:**
- Detect and structure long-form content
- Create specialized output items

---

## 4. MODEL MANAGEMENT ENDPOINTS & CAPABILITIES

### 4.1 Model Types Supported

✅ **Ollama Local Models**
- All ollama models available via `/ollama` proxy

✅ **OpenAI Compatible**
- OpenAI, Azure OpenAI, or any OpenAI-compatible endpoint
- Proxy via `/openai` endpoints

✅ **Direct/Custom Models**
- Support for direct model configurations
- Bypass routing logic

✅ **Arena Models**
- Load-balanced model selection
- Multiple URLs per model

### 4.2 Model Configuration Hierarchy

1. **System Level** - Global defaults
2. **Config Level** - Per-model settings (`/api/v1/config/models`)
3. **Request Level** - Runtime overrides

### 4.3 Model Metadata
```json
{
  "id": "gpt-4",
  "name": "GPT-4",
  "info": {
    "meta": {
      "description": "Most capable model",
      "tags": ["gpt", "reasoning"],
      "capabilities": ["vision", "function_calling"]
    },
    "params": {
      "temperature": 0.7,
      "top_p": 1.0,
      "max_tokens": 8096,
      "stream_response": true,
      "function_calling": "native"
    }
  },
  "owned_by": "openai",
  "external": true,
  "urlIdx": 0
}
```

### 4.4 Model Access Control

- Role-based filtering (admin/user)
- Per-user group filters
- Permission grants via access control

---

## 5. USER & AUTHENTICATION ENDPOINTS

### 5.1 Authentication Methods

✅ **Bearer Tokens** - Standard JWT
✅ **OAuth 2.0** - Multiple providers supported
✅ **LDAP/Active Directory** - Enterprise
✅ **OIDC** - Identity providers
✅ **SCIM 2.0** - User provisioning

### 5.2 Key Auth Endpoints

- **POST `/api/v1/auth/login`** - Password login
- **GET `/oauth/{provider}/login/callback`** - OAuth callback
- **GET `/api/v1/users/profile`** - Current user info
- **POST `/api/v1/users/`** - Create user (admin)

### 5.3 User Permission Model

```json
{
  "role": "user|admin|moderator",
  "permissions": {
    "chat": {"file_upload": true},
    "knowledge": {"create": true},
    "tools": {"manage": false}
  },
  "groups": ["team1", "team2"]
}
```

---

## 6. KNOWLEDGE BASE / RAG CAPABILITIES

### 6.1 Vector Database Support

**9 Vector Database Options:**
1. ✅ **ChromaDB** - Default, local
2. ✅ **PGVector** - PostgreSQL extension
3. ✅ **Qdrant** - Native cloud vector DB
4. ✅ **Milvus** - Open-source vector DB
5. ✅ **Elasticsearch** - (with vector support)
6. ✅ **OpenSearch** - AWS alternative
7. ✅ **Pinecone** - Managed vector DB
8. ✅ **S3Vector** - S3-based (experimental)
9. ✅ **Oracle 23ai** - Enterprise

### 6.2 Embedding Engines

| Engine | Status | Features |
|--------|--------|----------|
| **SentenceTransformers** | ✅ Default | Local, free, ~100+ models |
| **OpenAI** | ✅ Production | `text-embedding-3-small/large` |
| **Azure OpenAI** | ✅ Enterprise | Cloud-based embeddings |
| **Ollama** | ✅ Production | Local models |

### 6.3 Content Extraction Engines

| Engine | Supported Formats | Status |
|--------|------------------|--------|
| **Tika** | PDF, Office, etc. | ✅ Production |
| **Docling** | Modern PDF, Office | ✅ Advanced |
| **Document Intelligence** | Azure form parser | ✅ Enterprise |
| **Mistral OCR** | Images, scans | ✅ New |
| **MinerU** | Complex layouts | ✅ Advanced |
| **External Loaders** | Custom webhook | ✅ Extensible |

### 6.4 RAG Features

✅ **Hybrid Search**
- Vector similarity + BM25 keyword search
- Configurable weighting

✅ **Reranking**
- Cross-encoder reranking
- Top-K selection
- Relevance thresholding

✅ **Knowledge Bases**
- Organized document collections
- Access control per KB
- Embeddings stored with metadata

✅ **Built-in Tools**
- `query_knowledge_bases()` - Search all accessible KBs
- `query_knowledge_files()` - Search specific files
- Automatic context injection

### 6.5 RAG Configuration Options

```json
{
  "RAG_TOP_K": 3,              // Results to retrieve
  "RAG_TOP_K_RERANKER": 3,     // After reranking
  "RAG_RELEVANCE_THRESHOLD": 0.0,
  "RAG_HYBRID_BM25_WEIGHT": 0.5,  // 0.5 = 50% keyword, 50% vector
  "ENABLE_RAG_HYBRID_SEARCH": true,
  "RAG_EMBEDDING_ENGINE": "openai|ollama|azure_openai|",
  "RAG_EMBEDDING_MODEL": "text-embedding-3-small",
  "RAG_RERANKING_ENGINE": "sentences|cross-encoder|external",
  "RAG_RERANKING_MODEL": "ms-marco-MiniLM-L-12-v2"
}
```

---

## 7. FILE UPLOAD & PARSING CAPABILITIES

### 7.1 Supported File Types

**Documents:**
- ✅ PDF (with image extraction)
- ✅ Word (.docx, .doc)
- ✅ Excel (.xlsx)
- ✅ Markdown (.md)
- ✅ Text (.txt)
- ✅ JSON

**Code:**
- ✅ .py, .js, .ts, .java, etc.

**Media:**
- ✅ Audio (with transcription)
- ✅ Video (with transcription + metadata)
- ✅ Images (with OCR options)

### 7.2 File Upload Features

**Async Processing:**
```python
POST /api/v1/files/
  process=true              # Extract content
  process_in_background=true  # Non-blocking
  metadata={...}            # Knowledge base ID, etc.
```

**Status Tracking:**
```
GET /api/v1/files/{id}/process/status?stream=true
```

**Content Access:**
```
GET /api/v1/files/{id}/data/content  # Extracted text
```

### 7.3 Knowledge Base Integration

Files → Chunks → Embeddings → Vector DB

**Chunking Strategies:**
- Recursive character splitting (default)
- Token-based splitting
- Markdown header splitting
- Custom segment sizes (100-2000 tokens)

---

## 8. WEBHOOK & REAL-TIME FEATURES

### 8.1 Webhook Support

**Webhook Configuration:**
```
GET /api/webhook              # Get webhook URL
POST /api/webhook             # Set webhook URL
```

**Events Sent:**
- Chat completion
- File processing complete
- User actions
- Model events

### 8.2 Real-Time Capabilities

✅ **Socket.IO Integration**
- Real-time event emitter
- Chat updates streamed live
- Task status updates

✅ **Background Task Queue**
- Redis-based task management
- Long-running job tracking
- Async completions

---

## 9. BATCH & ASYNC PROCESSING ENDPOINTS

### 9.1 Batch File Processing

```
POST /api/v1/retrieval/process/files/batch
```
- Process multiple files at once
- Returns batch status
- Streaming results

### 9.2 Background Task System

| Endpoint | Purpose |
|----------|---------|
| **GET `/api/v1/tasks`** | List active tasks |
| **GET `/api/v1/tasks/chat/{chat_id}`** | Tasks for chat |
| **POST `/api/v1/tasks/stop/{id}`** | Stop task |

**Available Background Tasks:**
- Title generation
- Query generation for RAG
- Image generation
- Auto-completion
- File processing

### 9.3 Chat Statistics Export

```
GET /api/v1/chats/stats/export?stream=true&updated_at=timestamp
```
- JSONL streaming format
- Pagination support
- Full analytics data

---

## 10. ADVANCED FEATURES CURRENTLY UNDERUTILIZED

### 10.1 Function Calling & Tool Use

**Current Status:** ✅ Fully Implemented

Not being used in your basic message format.

**What you can add:**
```json
{
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_weather",
      "description": "Get current weather",
      "parameters": {...}
    }
  }],
  "tool_choice": "auto"  // auto, required, function name
}
```

**Response will include:**
```json
{
  "choices": [{
    "message": {
      "tool_calls": [{
        "id": "call-123",
        "function": {"name": "get_weather", "arguments": "..."}
      }]
    }
  }]
}
```

### 10.2 Reasoning Tags (Extended Thinking)

**Detection of Special Blocks:**
```
<think>...</think>     # Internal reasoning
<solution>...</solution> # Final answer
<code>...</code>        # Code execution
```

**Enable with:**
```json
{
  "params": {
    "reasoning_tags": ["<think>", "</think>"]
  }
}
```

### 10.3 File Context in Messages

```json
{
  "messages": [...],
  "files": [
    {
      "id": "file-xxx",
      "name": "document.pdf",
      "type": "document"
    }
  ]
}
```

Files are automatically included in context, extracting text and making searchable.

### 10.4 Knowledge Base Auto-Injection

Instead of manual RAG queries:
```json
{
  "knowledge_ids": ["kb-123", "kb-456"]
}
```

OpenWebUI automatically:
1. Retrieves relevant documents
2. Injects as context
3. Tracks sources
4. Returns citations

### 10.5 Model Switching Based on Task

```json
{
  "model_ids": ["gpt-4", "gpt-3.5-turbo"],  // Multiple models
  "selection_strategy": "round_robin|cost|capability"
}
```

### 10.6 Chat Metadata & Tracking

```json
{
  "metadata": {
    "chat_id": "identify-existing-chat",
    "message_id": "for-continuing",
    "session_id": "group-messages",
    "user_id": "track-user"
  }
}
```

Enables:
- Full session tracking
- Chat history linking
- User behavior analysis
- Message continuation

### 10.7 Custom System Prompts per Model

Via `/api/v1/config/models`:
```json
{
  "model_id": {
    "system_message": "You are a specific type of assistant..."
  }
}
```

### 10.8 Vision/Image Handling

**In messages:**
```json
{
  "content": [
    {"type": "text", "text": "What's in this image?"},
    {
      "type": "image_url",
      "image_url": {"url": "https://..."}
    }
  ]
}
```

**With file uploads:**
OpenWebUI extracts images from documents.

### 10.9 Token Usage Analytics

```
GET /api/v1/analytics/tokens?start_date=X&end_date=Y
```

Returns per-model token costs (input/output breakdowns).

### 10.10 Interactive Chat Actions

```
POST /api/chat/actions/{action_id}
```

Custom actions (regenerate, continue, summarize, etc.)

---

## 11. CURRENT USAGE vs. FULL POTENTIAL

### Your Current Implementation

```python
requests.post(
    api_url,
    json={"messages": [{"role": "user", "content": "..."}]}
)
```

**Features Used:** ✅ Basic
- ❌ No streaming
- ❌ No tool calling
- ❌ No RAG knowledge bases
- ❌ No file attachment
- ❌ No metadata tracking
- ❌ No failure retries
- ❌ No token accounting

### Recommended Enhancements (Priority Order)

**Phase 1 - Quick Wins (1-2 Hours Each):**

1. **Enable Streaming** `"stream": true`
   - Better UX with real-time chunks
   - Use `SSE` reader to capture tokens

2. **Add Metadata Tracking**
   - Track `chat_id`, `message_id`, `session_id`
   - Link to MeshCore room/contact data

3. **File Attachment Support**
   - Upload files via `/api/v1/files/` before chat
   - Reference in `files` parameter

**Phase 2 - Knowledge Integration (4-8 Hours Each):**

4. **Embed Knowledge Bases**
   - Create KB via `/api/v1/knowledge/create`
   - Add files with `/api/v1/knowledge/{id}/file/add`
   - Pass `knowledge_ids` in chat request

5. **Implement Function Calling**
   - Define tools matching room capabilities
   - Parse `tool_calls` in responses
   - Execute and report results

**Phase 3 - Advanced Features (8+ Hours Each):**

6. **RAG with Hybrid Search**
   - Configure vector DB and embeddings
   - Enable BM25 keyword fallback
   - Implement reranking

7. **Analytics & Insights**
   - Track token usage per model
   - Monitor chat quality metrics
   - Generate usage reports

---

## 12. API AUTHENTICATION & SECURITY

### 12.1 Token Management

**Get Token via:**
- Web UI login
- OAuth providers
- API key endpoint

**Token Format:** JWT Bearer

**Usage:**
```
Authorization: Bearer <token>
```

### 12.2 Required Permissions

| Feature | Permission | Role |
|---------|-----------|------|
| Chat | `default` | user+ |
| Files | `chat.file_upload` | user+ |
| Knowledge | `knowledge.create` | user+admin |
| Admin Config | `admin` | admin |

---

## 13. MISSING/UNDER-IMPLEMENTED FEATURES

### 13.1 NOT Public API (Internal Only)

- **Pipeline Management** - Internal function pipelines
- **Model Training** - Fine-tuning endpoints
- **Source Code Integration** - Direct repo access
- **Event Logging** - Low-level event stream

### 13.2 Potential Gaps

- **Multi-modal input** - Limited audio input in messages
- **Conversation branching** - No native branch points
- **Collaborative editing** - Single-user chats
- **Voice chat** - Audio-only conversations not first-class

---

## 14. PERFORMANCE CONSIDERATIONS

### 14.1 Rate Limiting

- No explicit rate limits documented
- Redis-backed task queue for scalability
- Async processing for heavy operations

### 14.2 Request Timeouts

- Configurable `AIOHTTP_CLIENT_TIMEOUT`
- Default varies by operation type
- Streaming has different timeout handling

### 14.3 Data Size Limits

- File uploads: Configurable max size (typically 512MB)
- Message length: Model-dependent (typically 4K-200K tokens)
- Batch operations: Limited to reasonable concurrency

---

## 15. RECOMMENDATIONS FOR MESHCORE INTEGRATION

### Short Term (This Week)

1. ✅ Add streaming support to catch real-time tokens
2. ✅ Implement metadata tracking for chat linkage
3. ✅ Add error handling & retry logic
4. ✅ Log token usage for billing

### Medium Term (This Month)

5. ✅ Create knowledge bases for room context
6. ✅ Implement file attachment from room messages
7. ✅ Add function calling for room-specific actions
8. ✅ Set up basic analytics dashboard

### Long Term (This Quarter)

9. ✅ Integrate vector search for room history
10. ✅ Implement RAG with custom reranking
11. ✅ Add multi-modal message support
12. ✅ Build chat quality metrics

---

## CONCLUSION

OpenWebUI provides a **production-grade API** with far more capability than your current basic integration. The most impactful improvements would be:

1. **Streaming** - Better responsiveness
2. **Metadata tracking** - Full chat history linking
3. **Knowledge bases** - Room context awareness
4. **Function calling** - Room-specific actions
5. **RAG integration** - Contextual responses using room history

Each feature roughly doubles the capabilities, with streaming and metadata as foundational prerequisites for the others.

