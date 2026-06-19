import './style.css'
import { setupAgentChat } from './chat.ts'

const app = document.querySelector<HTMLDivElement>('#app')
if (app) {
  void setupAgentChat(app)
}
