import { io } from "socket.io-client";

import { API_URL, getBearerAccessToken } from "./api-client";

export const uiSocket = io(`${API_URL}/ui`, {
  transports: ["websocket"],
  withCredentials: true,
  auth: (callback) => {
    const token = getBearerAccessToken();
    callback(token ? {token} : {});
  },
  autoConnect: false,
  reconnection: true,
  reconnectionDelay: 1_000,
  reconnectionDelayMax: 10_000,
});
