import React, { useRef, useEffect } from 'react';

export interface ChatMessage {
    role: 'user' | 'agent';
    content: string;
}

interface ChatPanelProps {
    chatWidth: number;
    setChatWidth: (width: number) => void;
    isDragging: boolean;
    setIsDragging: (val: boolean) => void;
    chatMessages: ChatMessage[];
    setChatMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
    chatInput: string;
    setChatInput: (val: string) => void;
    handleChatFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
    sendChatMessage: (e: React.FormEvent) => void;
    agentTyping: boolean;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
    chatWidth,
    setChatWidth,
    isDragging,
    setIsDragging,
    chatMessages,
    setChatMessages,
    chatInput,
    setChatInput,
    handleChatFileUpload,
    sendChatMessage,
    agentTyping
}) => {
    const chatEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [chatMessages, agentTyping]);

    return (
        <aside
            style={{ width: `${chatWidth}px` }}
            className={`bg-card border-l border-border flex flex-col shadow-[0_10px_40px_-10px_rgba(0,0,0,0.1)] relative z-30 transition-colors duration-300 hidden xl:flex flex-shrink-0 ${isDragging ? 'select-none' : ''}`}
        >
            <div
                className="absolute -left-1 top-0 bottom-0 w-2 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 z-50 transition-colors"
                role="separator" aria-label="Resize chat panel" aria-orientation="vertical" tabIndex={0} aria-valuemin={300} aria-valuemax={800} aria-valuenow={chatWidth}
                onKeyDown={e => {
                    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                        e.preventDefault();
                        setChatWidth(Math.max(300, Math.min(800, chatWidth + (e.key === 'ArrowLeft' ? 20 : -20))));
                    }
                }}
                onMouseDown={() => setIsDragging(true)}
            ></div>

            <div className="p-4 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-green-500 shadow-[0_0_8px_#22c55e] animate-pulse"></div>
                    <h2 className="font-bold text-sm text-foreground">Demo Agent</h2>
                    <span className="text-[10px] bg-primary/10 text-primary px-2 py-0.5 rounded-md font-bold uppercase border border-primary/20">Simulated</span>
                </div>
                <button onClick={() => setChatMessages([])} className="text-muted-foreground hover:text-foreground text-xs font-bold border border-transparent hover:border-border px-2 py-1 rounded transition-colors">Clear</button>
            </div>

            <div role="log" aria-live="polite" aria-label="Demo conversation" className="flex-1 overflow-y-auto p-5 space-y-6 bg-muted/10">
                {chatMessages.map((msg, idx) => (
                    <div key={idx} className={`flex gap-3 text-sm ${msg.role === 'user' ? 'flex-row-reverse' : ''} animate-in`}>
                        <div className={`w-8 h-8 rounded-xl flex-shrink-0 flex items-center justify-center border shadow-sm ${msg.role === 'user' ? 'bg-background border-border text-foreground' : 'bg-primary border-transparent text-primary-foreground'}`}>
                            <i aria-hidden="true" className={msg.role === 'user' ? 'ri-user-line text-sm' : 'ri-robot-2-line text-sm'}></i>
                        </div>
                        <div className={`${msg.role === 'user' ? 'bg-primary text-primary-foreground rounded-tr-sm' : 'bg-card border border-border text-foreground rounded-tl-sm'} p-3.5 rounded-2xl max-w-[85%] font-medium text-sm leading-relaxed shadow-sm`}>
                            <p>{msg.content}</p>
                        </div>
                    </div>
                ))}

                {agentTyping && (
                    <div className="flex gap-3 text-sm animate-in">
                        <div className="w-8 h-8 rounded-xl flex-shrink-0 flex items-center justify-center border shadow-sm bg-primary border-transparent text-primary-foreground">
                            <i aria-hidden="true" className="ri-robot-2-line text-sm"></i>
                        </div>
                        <div className="bg-card border border-border text-foreground rounded-tl-sm p-3.5 rounded-2xl font-medium text-sm shadow-sm flex items-center gap-1.5 h-12">
                            <div className="w-1.5 h-1.5 bg-muted-foreground rounded-full animate-bounce [animation-delay:-0.3s]"></div>
                            <div className="w-1.5 h-1.5 bg-muted-foreground rounded-full animate-bounce [animation-delay:-0.15s]"></div>
                            <div className="w-1.5 h-1.5 bg-muted-foreground rounded-full animate-bounce"></div>
                        </div>
                    </div>
                )}

                <div ref={chatEndRef}></div>
            </div>

            <div className="p-4 border-t border-border bg-card">
                <form onSubmit={sendChatMessage} className="relative flex items-center bg-background border border-border rounded-xl focus-within:ring-2 focus-within:ring-primary/40 transition-all shadow-sm">
                    <label className="absolute left-1.5 w-9 h-9 rounded-lg flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-colors z-10" title="Attach file">
                        <i aria-hidden="true" className="ri-attachment-2 text-lg"></i>
                        <input
                            type="file" aria-label="Attach demo document" disabled={agentTyping}
                            className="sr-only"
                            onChange={handleChatFileUpload}
                            accept=".pdf,.png,.jpg,.jpeg,.csv,.xlsx,.xls,.txt"
                        />
                    </label>

                    <input
                        type="text"
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        placeholder="Message Bridge (Ctrl+K)..."
                        className="w-full bg-transparent py-3 pl-12 pr-12 text-sm focus:outline-none text-foreground font-medium"
                        id="chat-input" aria-label="Message the demo agent"
                    />
                    <button aria-label="Send message" type="submit" disabled={!chatInput.trim() || agentTyping} className={`absolute right-1.5 w-8 h-8 rounded-lg flex items-center justify-center transition-all ${chatInput.trim() && !agentTyping ? 'bg-primary text-primary-foreground hover:opacity-90 shadow-sm' : 'text-muted-foreground cursor-not-allowed'}`}>
                        <i aria-hidden="true" className="ri-send-plane-fill text-sm"></i>
                    </button>
                </form>
            </div>
        </aside>
    );
};
