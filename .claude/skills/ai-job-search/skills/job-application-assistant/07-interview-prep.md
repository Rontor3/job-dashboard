# Interview Preparation Guide

<!-- SETUP: STAR examples are personalized by running /setup based on your actual experience -->

## STAR Format

Structure answers as: **Situation** (context), **Task** (your responsibility), **Action** (what you did), **Result** (outcome).

Keep answers to 1-2 minutes. Be specific. End with what you learned or would do differently.

## Ready-Made STAR Examples

<!-- Drafted by /setup from CV bullets on 2026-07-13. Refine/verify the numbers before an interview. -->

### 1. Health Fraud Pipeline (production ML ownership, impact)
**S:** Health-insurance fraud/repudiation detection at Tata AIG relied on a baseline that missed cases and consumed heavy manual review.
**T:** Design and productionize a better-performing, automated fraud-detection system.
**A:** Architected modular, nested models; built a dynamic fraud mapper on AWS Lambda + DynamoDB; deployed real-time scoring endpoints on Lambda + API Gateway.
**R:** 30% higher recall than baseline, F1 0.6 on repudiation, ~500 man-hours/month saved via automation.
**Use for:** "Tell me about a project you owned end-to-end", "Describe production ML you shipped", "A time you improved a metric"

### 2. Offline RAG System (GenAI/LLM engineering, privacy constraints)
**S:** Needed to query sensitive data with an LLM without sending it to hosted APIs.
**T:** Build a private, efficient RAG system runnable locally.
**A:** Integrated Ollama Mistral with sentence-transformers multilingual embeddings; served a lightweight app via Streamlit.
**R:** Delivered a private, scalable RAG tool that eliminated hosted-API exposure for sensitive queries.
**Use for:** "Describe your GenAI/LLM experience", "A time you handled a hard constraint", "Show applied RAG knowledge"

### 3. ETF Optimization (quantitative modeling, measurable business result)
**S:** Passive equity/ETF investments were tracking the actual portfolio with no systematic edge.
**T:** Build an asset-selection and allocation model to beat the benchmark.
**A:** Used historical price and PE/PB data with Monte Carlo simulations to set parameters; backtested over 5 years; deployed after UAT.
**R:** 4% excess XIRR over the actual portfolio; still outperforming in production.
**Use for:** "A time you drove measurable impact", "Describe an analytical/quant project", "Owning something into production"

<!-- Add more STAR examples as needed (e.g. LLM Prompt Recovery / LoRA, Send-Time Optimization). Aim for 4-6 covering different competencies. -->

## Common Tough Questions

### "Why did you leave [previous company]?"
> [PREPARE YOUR ANSWER - be honest, forward-looking, no negativity about former employer]

### "You don't have [specific skill/experience]."
> [PREPARE YOUR ANSWER - acknowledge the gap, bridge to adjacent experience, show willingness to learn]

### "Where do you see yourself in 5 years?"
> [PREPARE YOUR ANSWER - show ambition aligned with the role's growth path]

### "What's your biggest weakness?"
> [PREPARE YOUR ANSWER - genuine weakness with concrete mitigation strategy]

### "Why this company specifically?"
> Customize per company. Must reference: specific projects, company values, market position, or team structure. Never give a generic answer.

## Questions You Should Ask Interviewers

### About the Role
- "What does a typical week look like in this role?"
- "What would success look like in the first 6 months?"
- "What's the biggest challenge the team is facing right now?"

### About the Team
- "How big is the team, and how do you divide work?"
- "What does the development/project lifecycle look like, from idea to production?"
- "How do you onboard new team members?"

### About Tech & Growth
- "What's your current tech stack for [relevant area]?"
- "Is there room to grow into more architectural or strategic decisions?"
- "How does the team stay current with new tools and methods?"

### About Culture (use these to prevent disappointment)
- "How would you describe the team culture?"
- "What does professional development look like here?"
- "Is there flexibility for remote/hybrid work?"
- "What's the balance between development/new projects and maintenance work?"
- "How would you describe the leadership style in this team?"
- "What do people who thrive here have in common?"

## Phone/Video Interview Tips
- Have STAR examples written out (use this file)
- Keep a glass of water nearby
- Smile when speaking (it changes your tone)
- Ask for clarification if a question is vague
- It's OK to take 5 seconds to think before answering
- End with: "Is there anything else you'd like to know about my background?"

## After the Application (Best Practice)

### Follow-Up Etiquette
- **Don't call to "stand out"** or to learn more about the role post-submission - this risks a negative impression
- If the employer specified a timeline, respect it and wait
- If no timeline was given and significant time has passed (2+ weeks), a brief call to ask about status is acceptable
- If you have genuinely new, relevant information to share, a short follow-up is fine

### Thank-You Notes
- When you receive any update (interview invitation, rejection, or status update), send a brief thank-you message
- Express appreciation for their time and the process
- Keep it short (2-3 sentences)

## Roleplay Guidelines
When the user asks for interview practice:
1. Ask which role/company to simulate
2. Start with easy warm-up questions ("Tell me about yourself")
3. Progress to role-specific technical questions
4. Include 1-2 behavioral questions using the competencies from the job posting
5. End with a tough question or curveball
6. After each answer, give brief feedback: what worked, what to sharpen
7. Suggest which STAR example would work best for each question
