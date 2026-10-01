import { io } from "socket.io-client";

import { API_URL, getAccessToken } from "./api-client";

export const uiSocket = io(`${API_URL}/ui`, {
  transports: ["websocket"],
  auth: (callback) => callback({ token: getAccessToken() }),
  autoConnect: false,
  reconnection: true,
  reconnectionDelay: 1_000,
  reconnectionDelayMax: 10_000,
});
