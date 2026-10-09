import React, { useState, useEffect, useRef } from 'react';
import {
  Mic,
  MicOff,
  Send,
  Sparkles,
  Bot,
  User,
  Calendar,
  Clock,
  Compass,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  Volume2,
  VolumeX,
  Layers,
  ArrowRight,
  Terminal,
} from 'lucide-react';

const STUDENTS = [
  {
    id: 'student_alice',
    name: 'Alice Rivera',
    dept: 'Computer Science, Sem 5',
    token: 'token-alice-demo-cs',
    avatar: 'AR',
    description: 'High workload, 4 classes/day, overdue DB assignment',
  },
  {
    id: 'student_bob',
    name: 'Bob Chen',
    dept: 'Electrical Eng, Sem 3',
    token: 'token-bob-demo-ee',
    avatar: 'BC',
    description: 'Balanced workload, completely free Friday',
  },
  {
    id: 'student_charlie',
    name: 'Charlie Davis',
    dept: 'Mechanical Eng, Sem 7',
    token: 'token-charlie-demo-me',
    avatar: 'CD',
    description: 'Light senior schedule, plenty of free study time',
  },
];

const PROMPT_CHIPS = [
  'What classes do I have today?',
  'Prepare my day',
  'Where is my Database Systems class?',
  'What assignments do I have due?',
  'When am I free today?',
  'Are any assignments overdue?',
];

export default function App() {
  const [selectedStudent, setSelectedStudent] = useState(STUDENTS[0]);
  const [mode, setMode] = useState('voice'); // 'voice' | 'screen'
  const [voiceSpeechEnabled, setVoiceSpeechEnabled] = useState(true);
  const [isListening, setIsListening] = useState(false);

  // Chat State
  const [inputMessage, setInputMessage] = useState('');
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      role: 'assistant',
      text: "Hello Alice! I'm CampusMate, your AI college assistant. Ask me about your class schedule, upcoming assignments, classroom directions, or say 'Prepare my day' to generate an optimized daily study plan.",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [lastFailedMessage, setLastFailedMessage] = useState(null);

  // Live Tool Trace State
  const [toolTraces, setToolTraces] = useState([]);
  const [activeTab, setActiveTab] = useState('trace'); // 'trace' | 'plan'

  // Plan View State
  const [currentPlan, setCurrentPlan] = useState(null);
  const [completedBlocks, setCompletedBlocks] = useState(new Set());

  const messagesEndRef = useRef(null);

  // Auto-scroll chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Voice Speech Synthesis
  const speakText = (text) => {
    if (!voiceSpeechEnabled || mode !== 'voice' || !('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    window.speechSynthesis.speak(utterance);
  };

  // Browser Speech Recognition (Web Speech API)
  const toggleListening = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert('Speech recognition is not supported in this browser. Please type your query.');
      return;
    }

    if (isListening) {
      setIsListening(false);
      return;
    }

    try {
      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = 'en-US';

      recognition.onstart = () => setIsListening(true);
      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        setInputMessage(transcript);
        setIsListening(false);
        sendMessage(transcript);
      };
      recognition.onerror = () => setIsListening(false);
      recognition.onend = () => setIsListening(false);

      recognition.start();
    } catch (err) {
      console.error(err);
      setIsListening(false);
    }
  };

  // Student Switcher Handler
  const handleStudentChange = (student) => {
    setSelectedStudent(student);
    setToolTraces([]);
    setCurrentPlan(null);
    setMessages([
      {
        id: `switch_${Date.now()}`,
        role: 'assistant',
        text: `Switched session to ${student.name} (${student.dept}). All queries are now authenticated and scoped to your profile.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);
  };

  // Send Message & Connect to Agent SSE Stream
  const sendMessage = async (overrideText = null) => {
    const textToSend = overrideText || inputMessage;
    if (!textToSend.trim() || isLoading) return;

    const userMsg = {
      id: `usr_${Date.now()}`,
      role: 'user',
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputMessage('');
    setIsLoading(true);
    setLastFailedMessage(null);

    // Initial placeholder for assistant response
    const assistantMsgId = `asst_${Date.now()}`;

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: textToSend,
          token: selectedStudent.token,
          mode: mode,
        }),
      });

      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finalContent = '';

      const processBlock = (block) => {
        if (!block.trim()) return;
        const eventMatch = block.match(/event:\s*([^\r\n]+)/);
        const dataMatch = block.match(/data:\s*([^\r\n]+)/);

        const eventType = eventMatch ? eventMatch[1].trim() : 'message';
        if (!dataMatch) return;

        try {
          const data = JSON.parse(dataMatch[1].trim());

          if (eventType === 'tool_started') {
            setToolTraces((prev) => [
              {
                id: `tool_${Date.now()}_${Math.random()}`,
                name: data.tool,
                arguments: data.arguments,
                status: 'running',
                startTime: Date.now(),
              },
              ...prev,
            ]);
          } else if (eventType === 'tool_result') {
            let parsedResult = data.result;
            try {
              parsedResult = JSON.parse(data.result);
            } catch (e) {}

            // Update matching tool trace
            setToolTraces((prev) =>
              prev.map((t) =>
                t.name === data.tool && t.status === 'running'
                  ? {
                      ...t,
                      status: data.is_error ? 'error' : 'completed',
                      result: parsedResult,
                      latencyMs: data.latency_ms,
                    }
                  : t
              )
            );

            // If prepare_my_day tool succeeded, capture the structured plan
            if (data.tool === 'prepare_my_day' && !data.is_error && parsedResult) {
              setCurrentPlan(parsedResult);
              setActiveTab('plan');
            }
          } else if (eventType === 'final_answer') {
            finalContent = data.content;
            setMessages((prev) => {
              const existing = prev.find((m) => m.id === assistantMsgId);
              if (existing) {
                return prev.map((m) =>
                  m.id === assistantMsgId ? { ...m, text: finalContent } : m
                );
              } else {
                return [
                  ...prev,
                  {
                    id: assistantMsgId,
                    role: 'assistant',
                    text: finalContent,
                    timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                  },
                ];
              }
            });
            speakText(finalContent);
          } else if (eventType === 'error') {
            setMessages((prev) => [
              ...prev,
              {
                id: `err_${Date.now()}`,
                role: 'assistant',
                isError: true,
                text: data.error || 'Agent encountered an error processing your request.',
                timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
              },
            ]);
          }
        } catch (err) {
          console.warn('Error parsing SSE event:', err);
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        // Normalize CRLF to LF so chunk splitting works consistently across browsers and platforms
        buffer = buffer.replace(/\r\n/g, '\n');
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop() || '';

        for (const block of blocks) {
          processBlock(block);
        }
      }

      // Process any remaining event block in buffer upon stream completion
      if (buffer.trim()) {
        processBlock(buffer.replace(/\r\n/g, '\n'));
      }
    } catch (err) {
      console.error(err);
      setLastFailedMessage(textToSend);
      setMessages((prev) => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          role: 'assistant',
          isError: true,
          text: `I ran into an issue reaching the assistant: ${err.message}. Please verify the agent service is active.`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const toggleBlockDone = (idx) => {
    setCompletedBlocks((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Top Navbar */}
      <header
        style={{
          borderBottom: '1px solid var(--border-subtle)',
          background: 'rgba(10, 13, 20, 0.85)',
          backdropFilter: 'blur(12px)',
          position: 'sticky',
          top: 0,
          zIndex: 50,
          padding: '12px 24px',
        }}
      >
        <div style={{ maxWidth: 1400, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          {/* Logo & Hackathon Badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: 'var(--radius-md)',
                background: 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 0 20px rgba(99, 102, 241, 0.4)',
              }}
            >
              <Sparkles size={22} color="#fff" />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em' }}>
                  CampusMate
                </h1>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: '2px 8px',
                    borderRadius: 999,
                    background: 'rgba(99, 102, 241, 0.18)',
                    color: '#818cf8',
                    border: '1px solid rgba(99, 102, 241, 0.3)',
                  }}
                >
                  Alexa+ MCP Track
                </span>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                MCP Spec 2025-11-25 • Streamable HTTP • Deterministic Planner
              </p>
            </div>
          </div>

          {/* Right Controls: Mode Toggle & Student Switcher */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            {/* Mode Toggle (Voice vs Screen) */}
            <div
              style={{
                display: 'flex',
                background: 'var(--bg-secondary)',
                borderRadius: var_radius_sm,
                border: '1px solid var(--border-subtle)',
                padding: 3,
              }}
            >
              <button
                id="btn-voice-mode"
                onClick={() => setMode('voice')}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '6px 12px',
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 600,
                  color: mode === 'voice' ? '#fff' : 'var(--text-muted)',
                  background: mode === 'voice' ? 'var(--primary)' : 'transparent',
                  transition: 'all 0.2s',
                }}
              >
                <Mic size={14} /> Voice Mode
              </button>
              <button
                id="btn-screen-mode"
                onClick={() => setMode('screen')}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '6px 12px',
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 600,
                  color: mode === 'screen' ? '#fff' : 'var(--text-muted)',
                  background: mode === 'screen' ? 'var(--primary)' : 'transparent',
                  transition: 'all 0.2s',
                }}
              >
                <Layers size={14} /> Screen Mode
              </button>
            </div>

            {/* TTS Audio Mute/Unmute */}
            {mode === 'voice' && (
              <button
                id="btn-toggle-tts"
                onClick={() => setVoiceSpeechEnabled(!voiceSpeechEnabled)}
                title={voiceSpeechEnabled ? 'Mute speech' : 'Enable spoken voice'}
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 8,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border-subtle)',
                  color: voiceSpeechEnabled ? 'var(--accent-cyan)' : 'var(--text-muted)',
                }}
              >
                {voiceSpeechEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
              </button>
            )}

            {/* Student Switcher Dropdown */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 500 }}>Student:</span>
              <select
                id="select-student"
                value={selectedStudent.id}
                onChange={(e) => {
                  const s = STUDENTS.find((st) => st.id === e.target.value);
                  if (s) handleStudentChange(s);
                }}
                style={{
                  background: 'var(--bg-secondary)',
                  color: '#fff',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 8,
                  padding: '6px 12px',
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: 'pointer',
                }}
              >
                {STUDENTS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.dept})
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </header>

      {/* Main Workspace Layout */}
      <main style={{ flex: 1, maxWidth: 1400, width: '100%', margin: '0 auto', padding: '24px 20px', display: 'grid', gridTemplateColumns: 'minmax(380px, 1.2fr) minmax(360px, 1fr)', gap: 24 }}>
        
        {/* LEFT COLUMN: Simulated Voice & Chat Assistant */}
        <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
          
          {/* Active Student Card Banner */}
          <div
            className="glass-panel"
            style={{
              padding: '12px 18px',
              marginBottom: 14,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: '50%',
                  background: 'linear-gradient(135deg, #4f46e5, #06b6d4)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 700,
                  fontSize: 14,
                }}
              >
                {selectedStudent.avatar}
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{selectedStudent.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{selectedStudent.description}</div>
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <span
                style={{
                  fontSize: 11,
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--accent-emerald)',
                  background: 'rgba(16, 185, 129, 0.1)',
                  padding: '3px 8px',
                  borderRadius: 6,
                  border: '1px solid rgba(16, 185, 129, 0.2)',
                }}
              >
                Bearer Auth Active
              </span>
            </div>
          </div>

          {/* Chat Messages Feed */}
          <div
            className="glass-panel"
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: 20,
              display: 'flex',
              flexDirection: 'column',
              gap: 16,
              borderBottomLeftRadius: 0,
              borderBottomRightRadius: 0,
            }}
          >
            {messages.map((m) => (
              <div
                key={m.id}
                style={{
                  display: 'flex',
                  gap: 12,
                  alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '85%',
                }}
              >
                {m.role === 'assistant' && (
                  <div
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 8,
                      background: m.isError ? 'rgba(244, 63, 94, 0.2)' : 'rgba(99, 102, 241, 0.2)',
                      border: `1px solid ${m.isError ? 'rgba(244, 63, 94, 0.4)' : 'rgba(99, 102, 241, 0.4)'}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                    }}
                  >
                    <Bot size={18} color={m.isError ? 'var(--accent-rose)' : 'var(--primary)'} />
                  </div>
                )}

                <div>
                  <div
                    style={{
                      padding: '12px 16px',
                      borderRadius: 14,
                      fontSize: 14,
                      lineHeight: 1.55,
                      background:
                        m.role === 'user'
                          ? 'linear-gradient(135deg, #6366f1, #4f46e5)'
                          : m.isError
                          ? 'rgba(244, 63, 94, 0.1)'
                          : 'var(--bg-secondary)',
                      color: m.isError ? '#fda4af' : 'var(--text-primary)',
                      border: `1px solid ${
                        m.role === 'user'
                          ? 'transparent'
                          : m.isError
                          ? 'rgba(244, 63, 94, 0.3)'
                          : 'var(--border-subtle)'
                      }`,
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {m.text}
                  </div>
                  <div
                    style={{
                      fontSize: 10,
                      color: 'var(--text-muted)',
                      marginTop: 4,
                      textAlign: m.role === 'user' ? 'right' : 'left',
                    }}
                  >
                    {m.timestamp}
                  </div>
                </div>

                {m.role === 'user' && (
                  <div
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 8,
                      background: 'rgba(255, 255, 255, 0.1)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                    }}
                  >
                    <User size={18} color="#fff" />
                  </div>
                )}
              </div>
            ))}

            {/* Active Loading / Thinking Pulse */}
            {isLoading && (
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 8,
                    background: 'rgba(99, 102, 241, 0.2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Bot size={18} color="var(--primary)" />
                </div>
                <div
                  style={{
                    padding: '10px 16px',
                    borderRadius: 14,
                    background: 'var(--bg-secondary)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: 13,
                    color: 'var(--text-secondary)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <div className="voice-wave" style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--primary)' }} />
                  Processing query over MCP protocol...
                </div>
              </div>
            )}

            {/* Retry Button on Error */}
            {lastFailedMessage && !isLoading && (
              <div style={{ display: 'flex', justifyContent: 'center', margin: '8px 0' }}>
                <button
                  id="btn-retry"
                  onClick={() => sendMessage(lastFailedMessage)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '8px 16px',
                    borderRadius: 8,
                    fontSize: 13,
                    fontWeight: 600,
                    background: 'rgba(244, 63, 94, 0.15)',
                    color: '#fb7185',
                    border: '1px solid rgba(244, 63, 94, 0.3)',
                  }}
                >
                  <RotateCcw size={14} /> Retry Last Query
                </button>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Example Prompt Chips */}
          <div
            style={{
              padding: '10px 14px',
              background: 'rgba(16, 21, 34, 0.95)',
              borderLeft: '1px solid var(--border-subtle)',
              borderRight: '1px solid var(--border-subtle)',
              display: 'flex',
              gap: 8,
              overflowX: 'auto',
              whiteSpace: 'nowrap',
            }}
          >
            {PROMPT_CHIPS.map((chip, idx) => (
              <button
                key={idx}
                id={`chip-${idx}`}
                onClick={() => sendMessage(chip)}
                disabled={isLoading}
                style={{
                  fontSize: 12,
                  padding: '5px 12px',
                  borderRadius: 999,
                  background: 'rgba(255, 255, 255, 0.04)',
                  color: 'var(--text-secondary)',
                  border: '1px solid var(--border-subtle)',
                  transition: 'all 0.15s ease',
                }}
                onMouseOver={(e) => {
                  e.currentTarget.style.background = 'rgba(99, 102, 241, 0.15)';
                  e.currentTarget.style.color = '#fff';
                  e.currentTarget.style.borderColor = 'rgba(99, 102, 241, 0.4)';
                }}
                onMouseOut={(e) => {
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)';
                  e.currentTarget.style.color = 'var(--text-secondary)';
                  e.currentTarget.style.borderColor = 'var(--border-subtle)';
                }}
              >
                {chip}
              </button>
            ))}
          </div>

          {/* Chat Input Bar */}
          <div
            className="glass-panel"
            style={{
              borderTopLeftRadius: 0,
              borderTopRightRadius: 0,
              padding: 12,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              borderTop: '1px solid rgba(255, 255, 255, 0.05)',
            }}
          >
            {/* Mic Button for Simulated Voice Input */}
            <button
              id="btn-voice-input"
              onClick={toggleListening}
              title={isListening ? 'Listening... click to stop' : 'Click to speak'}
              style={{
                width: 42,
                height: 42,
                borderRadius: '50%',
                background: isListening ? 'var(--accent-rose)' : 'rgba(99, 102, 241, 0.15)',
                border: `1px solid ${isListening ? 'var(--accent-rose)' : 'rgba(99, 102, 241, 0.4)'}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                transition: 'all 0.2s',
              }}
              className={isListening ? 'voice-wave' : ''}
            >
              {isListening ? <MicOff size={18} /> : <Mic size={18} />}
            </button>

            <input
              id="input-user-message"
              type="text"
              placeholder={isListening ? 'Listening to your voice...' : 'Ask CampusMate anything (or select a prompt above)...'}
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
              disabled={isLoading}
              style={{
                flex: 1,
                background: 'transparent',
                border: 'none',
                color: '#fff',
                fontSize: 14,
                padding: '8px 12px',
              }}
            />

            <button
              id="btn-send-message"
              onClick={() => sendMessage()}
              disabled={isLoading || !inputMessage.trim()}
              style={{
                width: 40,
                height: 40,
                borderRadius: 10,
                background: inputMessage.trim() ? 'var(--primary)' : 'rgba(255, 255, 255, 0.05)',
                color: inputMessage.trim() ? '#fff' : 'var(--text-muted)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.2s',
              }}
            >
              <Send size={16} />
            </button>
          </div>
        </div>

        {/* RIGHT COLUMN: Tabbed Trace & Daily Plan View */}
        <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
          {/* Tab Navigation Header */}
          <div
            style={{
              display: 'flex',
              gap: 8,
              borderBottom: '1px solid var(--border-subtle)',
              paddingBottom: 10,
              marginBottom: 14,
            }}
          >
            <button
              id="tab-trace"
              onClick={() => setActiveTab('trace')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 16px',
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 600,
                background: activeTab === 'trace' ? 'rgba(99, 102, 241, 0.15)' : 'transparent',
                color: activeTab === 'trace' ? '#818cf8' : 'var(--text-muted)',
                border: `1px solid ${activeTab === 'trace' ? 'rgba(99, 102, 241, 0.4)' : 'transparent'}`,
              }}
            >
              <Terminal size={15} /> Live MCP Protocol Trace
              {toolTraces.length > 0 && (
                <span
                  style={{
                    background: 'var(--primary)',
                    color: '#fff',
                    fontSize: 10,
                    padding: '1px 6px',
                    borderRadius: 999,
                  }}
                >
                  {toolTraces.length}
                </span>
              )}
            </button>

            <button
              id="tab-plan"
              onClick={() => setActiveTab('plan')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 16px',
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 600,
                background: activeTab === 'plan' ? 'rgba(6, 182, 212, 0.15)' : 'transparent',
                color: activeTab === 'plan' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                border: `1px solid ${activeTab === 'plan' ? 'rgba(6, 182, 212, 0.4)' : 'transparent'}`,
              }}
            >
              <Calendar size={15} /> Daily Plan View
              {currentPlan && (
                <span
                  style={{
                    background: 'var(--accent-cyan)',
                    color: '#000',
                    fontSize: 10,
                    fontWeight: 700,
                    padding: '1px 6px',
                    borderRadius: 999,
                  }}
                >
                  Active
                </span>
              )}
            </button>
          </div>

          {/* TAB 1: Live Tool-Call Trace Panel */}
          {activeTab === 'trace' && (
            <div
              className="glass-panel"
              style={{
                flex: 1,
                overflowY: 'auto',
                padding: 16,
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>
                  STREAMABLE HTTP TOOL EXECUTIONS
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  Protocol: MCP 2025-11-25
                </span>
              </div>

              {toolTraces.length === 0 ? (
                <div
                  style={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--text-muted)',
                    fontSize: 13,
                    textAlign: 'center',
                    padding: 40,
                  }}
                >
                  <Terminal size={36} style={{ marginBottom: 12, opacity: 0.4 }} />
                  <div>No tool calls recorded yet.</div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    Try asking a question in the chat to see real-time MCP protocol exchanges.
                  </div>
                </div>
              ) : (
                toolTraces.map((trace) => (
                  <div
                    key={trace.id}
                    style={{
                      background: 'rgba(10, 13, 20, 0.65)',
                      borderRadius: 10,
                      border: '1px solid var(--border-subtle)',
                      padding: 14,
                    }}
                  >
                    {/* Trace Header */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: 13,
                            fontWeight: 600,
                            color: '#a5b4fc',
                          }}
                        >
                          {trace.name}
                        </span>
                        {trace.status === 'running' ? (
                          <span
                            className="pulse-active"
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              padding: '2px 6px',
                              borderRadius: 4,
                              background: 'rgba(245, 158, 11, 0.2)',
                              color: 'var(--accent-amber)',
                              border: '1px solid rgba(245, 158, 11, 0.4)',
                            }}
                          >
                            RUNNING
                          </span>
                        ) : trace.status === 'error' ? (
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              padding: '2px 6px',
                              borderRadius: 4,
                              background: 'rgba(244, 63, 94, 0.2)',
                              color: 'var(--accent-rose)',
                            }}
                          >
                            FAILED
                          </span>
                        ) : (
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              padding: '2px 6px',
                              borderRadius: 4,
                              background: 'rgba(16, 185, 129, 0.15)',
                              color: 'var(--accent-emerald)',
                            }}
                          >
                            COMPLETED
                          </span>
                        )}
                      </div>

                      {trace.latencyMs !== undefined && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                          <Clock size={12} />
                          <span>{trace.latencyMs} ms</span>
                        </div>
                      )}
                    </div>

                    {/* Arguments Section */}
                    <div style={{ marginBottom: 6 }}>
                      <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                        Arguments
                      </span>
                      <pre
                        style={{
                          fontSize: 11,
                          fontFamily: 'var(--font-mono)',
                          background: '#07090e',
                          padding: '6px 10px',
                          borderRadius: 6,
                          overflowX: 'auto',
                          color: '#e2e8f0',
                          marginTop: 3,
                        }}
                      >
                        {JSON.stringify(trace.arguments, null, 2)}
                      </pre>
                    </div>

                    {/* Result Section */}
                    {trace.result !== undefined && (
                      <div>
                        <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                          Result Output
                        </span>
                        <pre
                          style={{
                            fontSize: 11,
                            fontFamily: 'var(--font-mono)',
                            background: '#07090e',
                            padding: '6px 10px',
                            borderRadius: 6,
                            overflowX: 'auto',
                            maxHeight: 160,
                            color: '#94a3b8',
                            marginTop: 3,
                          }}
                        >
                          {typeof trace.result === 'string'
                            ? trace.result
                            : JSON.stringify(trace.result, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}

          {/* TAB 2: Plan View Panel */}
          {activeTab === 'plan' && (
            <div
              className="glass-panel"
              style={{
                flex: 1,
                overflowY: 'auto',
                padding: 16,
                display: 'flex',
                flexDirection: 'column',
                gap: 14,
              }}
            >
              {!currentPlan ? (
                <div
                  style={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--text-muted)',
                    fontSize: 13,
                    textAlign: 'center',
                    padding: 40,
                  }}
                >
                  <Calendar size={36} style={{ marginBottom: 12, opacity: 0.4 }} />
                  <div>No daily plan generated yet.</div>
                  <button
                    onClick={() => sendMessage('Prepare my day')}
                    style={{
                      marginTop: 12,
                      padding: '8px 16px',
                      borderRadius: 8,
                      background: 'var(--primary)',
                      color: '#fff',
                      fontSize: 12,
                      fontWeight: 600,
                    }}
                  >
                    Generate Plan for Today
                  </button>
                </div>
              ) : (
                <>
                  {/* Plan Header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 10 }}>
                    <div>
                      <h3 style={{ fontSize: 16, fontWeight: 700 }}>
                        {currentPlan.mode === 'tomorrow_preview' ? 'Tomorrow Preview' : 'Schedule for Today'} ({currentPlan.date})
                      </h3>
                      <p style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                        Free Time Available: {Math.floor(currentPlan.total_free_minutes / 60)}h {currentPlan.total_free_minutes % 60}m
                      </p>
                    </div>

                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        padding: '4px 10px',
                        borderRadius: 6,
                        background: currentPlan.fits_everything ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                        color: currentPlan.fits_everything ? 'var(--accent-emerald)' : 'var(--accent-amber)',
                        border: `1px solid ${currentPlan.fits_everything ? 'rgba(16, 185, 129, 0.3)' : 'rgba(245, 158, 11, 0.3)'}`,
                      }}
                    >
                      {currentPlan.fits_everything ? '✓ All Tasks Fit' : '⚠ Deficit Detected'}
                    </span>
                  </div>

                  {/* Capacity Warnings Banner */}
                  {currentPlan.warnings && currentPlan.warnings.length > 0 && (
                    <div
                      style={{
                        padding: '12px 14px',
                        borderRadius: 10,
                        background: 'rgba(245, 158, 11, 0.12)',
                        border: '1px solid rgba(245, 158, 11, 0.3)',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: 10,
                        fontSize: 12,
                        color: '#fde68a',
                      }}
                    >
                      <AlertTriangle size={18} color="var(--accent-amber)" style={{ flexShrink: 0, marginTop: 1 }} />
                      <div>
                        {currentPlan.warnings.map((w, idx) => (
                          <div key={idx}>{w}</div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Timeline Blocks */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {currentPlan.schedule_blocks?.map((block, idx) => {
                      const isDone = completedBlocks.has(idx);
                      const isClass = block.type === 'class';
                      const isLunch = block.type === 'lunch';

                      return (
                        <div
                          key={idx}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: '12px 14px',
                            borderRadius: 10,
                            background: isDone
                              ? 'rgba(16, 185, 129, 0.05)'
                              : isClass
                              ? 'rgba(99, 102, 241, 0.08)'
                              : isLunch
                              ? 'rgba(245, 158, 11, 0.08)'
                              : 'rgba(6, 182, 212, 0.08)',
                            border: `1px solid ${
                              isDone
                                ? 'rgba(16, 185, 129, 0.25)'
                                : isClass
                                ? 'rgba(99, 102, 241, 0.25)'
                                : isLunch
                                ? 'rgba(245, 158, 11, 0.25)'
                                : 'rgba(6, 182, 212, 0.25)'
                            }`,
                            opacity: isDone ? 0.7 : 1,
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                            {/* Time badge */}
                            <div
                              style={{
                                fontFamily: 'var(--font-mono)',
                                fontSize: 12,
                                fontWeight: 600,
                                color: isClass ? '#818cf8' : isLunch ? 'var(--accent-amber)' : 'var(--accent-cyan)',
                                minWidth: 90,
                              }}
                            >
                              {block.start} - {block.end}
                            </div>

                            {/* Block Info */}
                            <div>
                              <div style={{ fontSize: 13, fontWeight: 600, textDecoration: isDone ? 'line-through' : 'none' }}>
                                {block.title}
                              </div>
                              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                {block.reason} {block.room ? `• ${block.building} (${block.room})` : `• ${block.duration_minutes}m`}
                              </div>
                            </div>
                          </div>

                          {/* Toggle PROPOSED vs DONE */}
                          {!isClass && (
                            <button
                              onClick={() => toggleBlockDone(idx)}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 4,
                                padding: '4px 10px',
                                borderRadius: 6,
                                fontSize: 11,
                                fontWeight: 700,
                                background: isDone ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255, 255, 255, 0.08)',
                                color: isDone ? 'var(--accent-emerald)' : 'var(--text-secondary)',
                                border: `1px solid ${isDone ? 'rgba(16, 185, 129, 0.4)' : 'rgba(255, 255, 255, 0.15)'}`,
                              }}
                            >
                              {isDone ? <CheckCircle2 size={12} /> : null}
                              {isDone ? 'DONE' : 'PROPOSED'}
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Unscheduled Tasks Section */}
                  {currentPlan.unscheduled_tasks && currentPlan.unscheduled_tasks.length > 0 && (
                    <div style={{ marginTop: 10 }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent-amber)', textTransform: 'uppercase' }}>
                        Unscheduled Due to Insufficient Free Time
                      </span>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
                        {currentPlan.unscheduled_tasks.map((u, idx) => (
                          <div
                            key={idx}
                            style={{
                              padding: '8px 12px',
                              borderRadius: 8,
                              background: 'rgba(245, 158, 11, 0.08)',
                              border: '1px solid rgba(245, 158, 11, 0.2)',
                              fontSize: 12,
                              display: 'flex',
                              justifyContent: 'space-between',
                            }}
                          >
                            <span>{u.title} ({u.subject})</span>
                            <span style={{ color: 'var(--accent-amber)', fontWeight: 600 }}>
                              Needs +{u.unfitted_minutes}m
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
const var_radius_sm = '8px';
