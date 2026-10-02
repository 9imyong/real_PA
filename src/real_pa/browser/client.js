'use strict';
const ui = id => document.getElementById(id);
let assistant = null;
let currentGeneration = -1;
const labels = { idle: '대기 중', listening: '듣는 중', thinking: '답변 준비 중', speaking: '말하는 중' };
function message(role, text) {
  ui('empty')?.remove();
  const bubble = document.createElement('div');
  bubble.className = `message ${role}`;
  bubble.textContent = text;
  ui('conversation').append(bubble);
  ui('conversation').scrollTop = ui('conversation').scrollHeight;
  return bubble;
}
function connected(value) {
  ui('start').disabled = value;
  ui('stop').disabled = ui('send').disabled = ui('interrupt').disabled = !value;
}
const client = new RealPAClient({
  outputSampleRate: 48000,
  onState: state => {
    ui('status').textContent = labels[state] || state;
    connected(client.isActive);
    ui('capture-state').textContent = client.isActive && client.microphone ? '마이크 켜짐' : '마이크 꺼짐';
  },
  onTranscript: (text, final) => {
    ui('partial').textContent = final ? '' : text;
    if (final && text.trim()) message('user', text);
  },
  onText: (text, reset) => {
    if (reset) {
      if (assistant && ['말하는 중', '답변 준비 중'].includes(ui('status').textContent)) assistant.classList.add('interrupted');
      assistant = null;
      currentGeneration = client._generation;
      return;
    }
    if (!assistant || currentGeneration !== client._generation) {
      assistant = message('assistant', '');
      currentGeneration = client._generation;
    }
    assistant.textContent += text;
    ui('conversation').scrollTop = ui('conversation').scrollHeight;
  },
  onError: text => {
    ui('notice').textContent = text;
    connected(false);
    ui('capture-state').textContent = '마이크 꺼짐';
  },
  onNotice: text => { ui('notice').textContent = text; },
});
ui('start').onclick = async () => {
  ui('notice').textContent = '';
  ui('status').textContent = '연결 중';
  ui('start').disabled = true;
  client.token = ui('token').value;
  client.microphone = ui('microphone').checked;
  await client.start();
  connected(client.isActive);
};
ui('stop').onclick = async () => { await client.stop(); connected(false); ui('partial').textContent = ''; };
ui('microphone').onchange = async () => {
  try {
    await client.setMicrophone(ui('microphone').checked);
    ui('capture-state').textContent = client.isActive && client.microphone ? '마이크 켜짐' : '마이크 꺼짐';
  } catch (error) {
    ui('microphone').checked = false;
    await client.setMicrophone(false);
    ui('notice').textContent = '마이크 권한과 반향 제거 지원을 확인해 주세요.';
  }
};
ui('interrupt').onclick = () => client.interrupt();
ui('composer').onsubmit = event => {
  event.preventDefault();
  const text = ui('text').value.trim();
  if (text && client.sendText(text)) { message('user', text); ui('text').value = ''; }
};
ui('text').onkeydown = event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); ui('composer').requestSubmit(); }
};
