# HeritageVoice AI: presentation (5 minutes)

The slides used to present the project, with what each one says and the speaker notes. The slide deck itself is a Claude artifact ([open it](https://claude.ai/artifact/Lht5ZxsiZQod3t4KjESkP8)); it is private until its owner shares it, so this page keeps the text in the repository.

7 slides, about 5 minutes 10 seconds when read at an unhurried pace.

| # | Slide | About |
| --- | --- | --- |
| 1 | Their Wisdom via their Voices, Always with us. | 25 s |
| 2 | Spoken knowledge is fading. We keep it, with consent. | 60 s |
| 3 | One small system, built in clear layers | 50 s |
| 4 | How the agents work together | 45 s |
| 5 | Two ways to search, fused into one list | 45 s |
| 6 | Only reviewed relationships, double-checked on every question | 45 s |
| 7 | It works end to end, and we measured it. | 40 s |

## 1. Their Wisdom via their Voices, Always with us.

**On the slide**

- Ask in your own language. Hear the voice you always wanted to hear.
- Connecting our ancestors to the generations still to come

**Speaker notes** (about 25 seconds)

Say it personally: think of a grandmother’s lullaby, a grandfather’s advice, a voice you wish you could hear again. Their voice and their advice can stay with every new generation. If asked: these are the real recorded voices, never an AI imitation of a person, and everything is shared with consent and with care. Option: open by reading this aloud: “The old songs, the farmer’s wisdom and the lessons of our elders, kept in their own voices for the generations still to come.” Then: Hello everyone. HeritageVoice AI is a platform that keeps the spoken knowledge of communities, their stories, songs, remedies and traditions, and lets anyone ask questions about it. This picture is the idea in one frame: an elder speaks, her voice is kept, and it becomes knowledge that connects to other knowledge. The key promise is in the tagline: every answer leads back to the real voice that said it. It is live today at heritagevoice.org.

## 2. Spoken knowledge is fading. We keep it, with consent.

**On the slide**

- Problem and solution
- The problem
- HeritageVoice AI
- Recordings nobody can search
- Transcribed, translated and searchable in your own language
- AI that guesses and invents
- Answers cite the exact recording and moment. Press play to hear it.
- No control over who hears
- Consent first. People approve. Families decide who hears.
- Their voices, always with us.

**Speaker notes** (about 60 seconds)

Traditional knowledge, remedies, songs, how a festival is done, is passed on by voice, and it is fading. Three things go wrong when we try to keep it, and each has an answer. One: recordings in many languages are locked away, nobody can search them. We transcribe and translate them so anyone can search in their own language. Two: a general AI guesses and can put words in an elder’s mouth. Our answers cite the exact recording and moment, and you can press play and hear the real voice. Three: the community often loses control of who can hear it. In our system the speaker gives consent first, a person approves before anything is searchable, and families decide who hears. Their voices, always with us.

## 3. One small system, built in clear layers

**On the slide**

- Architecture
- Use
- Streamlit app
- Library, Ask, Connections, record, review
- Amazon Cognito
- Sign-in on a separate secure domain
- Think
- FastAPI + worker
- API and background jobs
- LangGraph agents
- Seven agents, one job each, with fall-backs
- Amazon Transcribe
- Timed transcripts from speech
- Remember
- PostgreSQL
- The source of truth
- Pinecone
- Meaning search, rebuildable
- Neo4j
- Reviewed graph, rebuildable
- Private S3
- Audio, encrypted
- Runs on one small AWS instance. Built with Terraform. Deployed only by GitHub Actions, with no stored AWS keys.
- Live now: heritagevoice.org · demo library in 9 languages

**Speaker notes** (about 50 seconds)

The architecture has three layers. On top, what people use: a Streamlit web app and Amazon Cognito for sign-in. In the middle, the thinking: a FastAPI service with a background worker, seven small LangGraph agents that each have one job, plus the retrieval steps, and Amazon Transcribe for speech. At the bottom, memory. PostgreSQL is the source of truth, it holds the records, the consent and keyword search. Pinecone, for meaning-based search, and Neo4j, for the knowledge graph, are only copies that can be rebuilt from PostgreSQL, so losing one is not a disaster. Audio sits in a private, encrypted S3 bucket. The whole thing runs on one small AWS instance, built with Terraform and deployed only by GitHub Actions, so nobody pushes to production by hand.

## 4. How the agents work together

**On the slide**

- One question, followed step by step
- A family member asks, in English
- “What does it teach?” (right after reading the Tamil proverb about humility)
- Question rewriter
- Makes it stand alone: “What does the Tamil proverb about humility teach?”
- Supervisor
- Chooses the route: this is about a passage and a relationship, so use both searches.
- Hybrid RAG + GraphRAG
- Not agents, they find evidence: the passage where it is told, and the reviewed link “proverb teaches humility”. Duplicates are merged.
- Verifier
- Checks each claim against the evidence and drops anything the recordings do not support.
- Answer writer
- Writes the answer from the verified claims only. Code, not the AI, adds the citations.
- Answer: “It teaches humility.” with a link to the recording. When a recording is added, 3 more agents help earlier: translator, graph extractor and correction interpreter.

**Speaker notes** (about 45 seconds)

Instead of listing every agent, let me follow one question. A family member has just read a Tamil proverb and asks, in English: what does it teach? Step one, the question rewriter makes it stand alone, because on its own "what does it teach" means nothing. Step two, the supervisor decides the route. This question needs both a passage and a relationship, so it uses both searches. Step three, not an agent: hybrid RAG finds the passage where the proverb is told, and GraphRAG finds the reviewed link that says the proverb teaches humility. They are merged and duplicates removed. Step four, the verifier checks every claim against that evidence and throws away anything the recordings do not support. Step five, the answer writer phrases the answer from the verified claims only, and ordinary code adds the citation. So the answer is: it teaches humility, with a link to the recording. Three more agents help earlier, when a recording is added: the translator, the graph extractor and the correction interpreter. Two rules: agents never decide who may see what, because permissions are checked by code on the server; and if a step fails, the system degrades safely instead of guessing. The example is illustrative; the real wording of an answer will differ.

## 5. Two ways to search, fused into one list

**On the slide**

- Hybrid RAG, as built
- 1 · When a recording is published
- Approved text
- Transcript and English translation
- Chunking
- By speaker turn, 100–250 tokens. A segment is never split, so every chunk keeps its time in the audio.
- PostgreSQL
- Chunk text, for keyword search
- Pinecone
- 1,024-number vectors, no text. One namespace per community.
- Embedding model
- multilingual-e5-large, cosine similarity
- 2 · When someone asks a question
- Question
- Already rewritten to stand alone
- Keyword search
- PostgreSQL full text. Exact names and Tamil words. Top 20.
- Meaning search
- Question embedded, nearest vectors in Pinecone. Top 20.
- Permission check
- Every hit reloaded from PostgreSQL. Not approved, consented and readable by you: dropped.
- Rank fusion
- Reciprocal rank fusion merges both lists and removes duplicates.
- Best 5–8
- At most 2 per recording. On to the verifier.
- If Pinecone is down, keyword search carries on and the answer shows a warning. Pinecone can always be rebuilt from PostgreSQL.

**Speaker notes** (about 45 seconds)

This is how hybrid RAG is built, in two parts. First, when a recording is published, its approved transcript and English translation are cut into chunks by speaker turn, between 100 and 250 tokens. A segment is never split, so every chunk keeps its exact time in the audio. The chunks go two places: PostgreSQL keeps the text for keyword search, and an embedding model, multilingual-e5-large, turns each chunk into 1,024 numbers that go into Pinecone, with no text and one namespace per community. Second, when someone asks a question, two searches run. Keyword search in PostgreSQL is good at exact names and Tamil words. Meaning search in Pinecone finds the same idea in different words or another language. Each returns its top 20. Every hit is reloaded from PostgreSQL and dropped unless the reader is allowed to see it. Then reciprocal rank fusion merges the two lists, removes duplicates, and keeps the best five to eight passages, at most two from one recording. Those go to the verifier. If Pinecone is unavailable, keyword search carries on and the answer shows a warning, and Pinecone can always be rebuilt from PostgreSQL.

## 6. Only reviewed relationships, double-checked on every question

**On the slide**

- GraphRAG, as built
- 1 · Before the graph: proposed by AI, approved by people
- Published recording
- Only while consent allows AI processing
- Graph extractor
- The agent proposes links: who teaches what, what happened where. Each is only a proposal.
- A person reviews
- Approves or rejects each link. Nothing reaches the graph without a yes.
- PostgreSQL
- Approved links, with the supporting words. The source of truth.
- Neo4j
- A rebuildable copy: people, places and customs joined by 7 fixed link types.
- 2 · When someone asks a question
- Question
- Already rewritten to stand alone
- Find the names
- Names in the question are matched to nodes in the graph
- Follow the links
- One or two hops in Neo4j, up to 30 paths
- Re-check every link
- PostgreSQL confirms each is still approved and readable by you. One bad link drops the whole path.
- Passages + path
- Up to 8, each with the link that led to it. On to the merger.
- If Neo4j is not connected or is down, the question falls back to text search and the answer shows a warning. The graph can never show more than the text could.

**Speaker notes** (about 45 seconds)

GraphRAG has a careful life. First, a graph extractor agent reads a published recording, only while consent allows AI processing, and proposes relationships, like who teaches what or what happened where. These are only proposals. A person reviews each one and approves or rejects it. Approved links are saved in PostgreSQL with the exact words that support them, and PostgreSQL is the source of truth. Neo4j holds a rebuildable copy, with people, places and customs joined by seven fixed link types. When a question arrives, names in it are matched to nodes, and the graph is followed one or two steps, up to 30 paths. But Neo4j only suggests. Every link on every path is re-checked in PostgreSQL: still approved, still about the current transcript, and the supporting passage readable by this reader. If any link fails, the whole path is dropped. What survives becomes ordinary evidence, up to eight passages, each carrying the path that led to it, and goes to the merger. If Neo4j is not connected, the question falls back to text search with a warning. So the graph can never show more than the text could.

## 7. It works end to end, and we measured it.

**On the slide**

- Outcome
- 24/24
- test questions found the right recording in the top 5
- languages in the live demo library, all searchable
- 130ms
- typical search time, including the embedding call
- 1,400+
- automated tests guard privacy and behaviour
- Honest note: the test set is small and synthetic. With a simple word-matching index we found 23 of 24; real multilingual embeddings found all 24, including the Tamil paraphrase.

**Speaker notes** (about 40 seconds)

The outcome. The platform is live and works end to end. We built a synthetic demo library in nine languages: Tamil, Hindi, Telugu, Malayalam, Bengali, French, Spanish, Portuguese and English, and every one is searchable. We measured retrieval with a labelled set of questions: with real multilingual embeddings, all 24 answerable questions found the right recording in the top five, including a Tamil paraphrase that a simple word-matching index missed. A typical search takes about 130 milliseconds. Over 1,400 automated tests protect the behaviour, especially privacy. I want to be honest: this test set is small and synthetic, so it proves the pipeline works, it is not a promise about real recordings. The reports are published in the repository, dated and versioned.

---

The example answers on the agents slide are illustrative; real wording differs. The test voices in the demo are computer-generated, and the site says so under the player.
