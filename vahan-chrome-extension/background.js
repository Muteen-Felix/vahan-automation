(() => {
  var __defProp = Object.defineProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };

  // node_modules/engine.io-parser/build/esm/commons.js
  var PACKET_TYPES = /* @__PURE__ */ Object.create(null);
  PACKET_TYPES["open"] = "0";
  PACKET_TYPES["close"] = "1";
  PACKET_TYPES["ping"] = "2";
  PACKET_TYPES["pong"] = "3";
  PACKET_TYPES["message"] = "4";
  PACKET_TYPES["upgrade"] = "5";
  PACKET_TYPES["noop"] = "6";
  var PACKET_TYPES_REVERSE = /* @__PURE__ */ Object.create(null);
  Object.keys(PACKET_TYPES).forEach((key) => {
    PACKET_TYPES_REVERSE[PACKET_TYPES[key]] = key;
  });
  var ERROR_PACKET = { type: "error", data: "parser error" };

  // node_modules/engine.io-parser/build/esm/encodePacket.browser.js
  var withNativeBlob = typeof Blob === "function" || typeof Blob !== "undefined" && Object.prototype.toString.call(Blob) === "[object BlobConstructor]";
  var withNativeArrayBuffer = typeof ArrayBuffer === "function";
  var isView = (obj) => {
    return typeof ArrayBuffer.isView === "function" ? ArrayBuffer.isView(obj) : obj && obj.buffer instanceof ArrayBuffer;
  };
  var encodePacket = ({ type, data }, supportsBinary, callback) => {
    if (withNativeBlob && data instanceof Blob) {
      if (supportsBinary) {
        return callback(data);
      } else {
        return encodeBlobAsBase64(data, callback);
      }
    } else if (withNativeArrayBuffer && (data instanceof ArrayBuffer || isView(data))) {
      if (supportsBinary) {
        return callback(data);
      } else {
        return encodeBlobAsBase64(new Blob([data]), callback);
      }
    }
    return callback(PACKET_TYPES[type] + (data || ""));
  };
  var encodeBlobAsBase64 = (data, callback) => {
    const fileReader = new FileReader();
    fileReader.onload = function() {
      const content = fileReader.result.split(",")[1];
      callback("b" + (content || ""));
    };
    return fileReader.readAsDataURL(data);
  };
  function toArray(data) {
    if (data instanceof Uint8Array) {
      return data;
    } else if (data instanceof ArrayBuffer) {
      return new Uint8Array(data);
    } else {
      return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    }
  }
  var TEXT_ENCODER;
  function encodePacketToBinary(packet, callback) {
    if (withNativeBlob && packet.data instanceof Blob) {
      return packet.data.arrayBuffer().then(toArray).then(callback);
    } else if (withNativeArrayBuffer && (packet.data instanceof ArrayBuffer || isView(packet.data))) {
      return callback(toArray(packet.data));
    }
    encodePacket(packet, false, (encoded) => {
      if (!TEXT_ENCODER) {
        TEXT_ENCODER = new TextEncoder();
      }
      callback(TEXT_ENCODER.encode(encoded));
    });
  }

  // node_modules/engine.io-parser/build/esm/contrib/base64-arraybuffer.js
  var chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  var lookup = typeof Uint8Array === "undefined" ? [] : new Uint8Array(256);
  for (let i = 0; i < chars.length; i++) {
    lookup[chars.charCodeAt(i)] = i;
  }
  var decode = (base64) => {
    let bufferLength = base64.length * 0.75, len = base64.length, i, p = 0, encoded1, encoded2, encoded3, encoded4;
    if (base64[base64.length - 1] === "=") {
      bufferLength--;
      if (base64[base64.length - 2] === "=") {
        bufferLength--;
      }
    }
    const arraybuffer = new ArrayBuffer(bufferLength), bytes = new Uint8Array(arraybuffer);
    for (i = 0; i < len; i += 4) {
      encoded1 = lookup[base64.charCodeAt(i)];
      encoded2 = lookup[base64.charCodeAt(i + 1)];
      encoded3 = lookup[base64.charCodeAt(i + 2)];
      encoded4 = lookup[base64.charCodeAt(i + 3)];
      bytes[p++] = encoded1 << 2 | encoded2 >> 4;
      bytes[p++] = (encoded2 & 15) << 4 | encoded3 >> 2;
      bytes[p++] = (encoded3 & 3) << 6 | encoded4 & 63;
    }
    return arraybuffer;
  };

  // node_modules/engine.io-parser/build/esm/decodePacket.browser.js
  var withNativeArrayBuffer2 = typeof ArrayBuffer === "function";
  var decodePacket = (encodedPacket, binaryType) => {
    if (typeof encodedPacket !== "string") {
      return {
        type: "message",
        data: mapBinary(encodedPacket, binaryType)
      };
    }
    const type = encodedPacket.charAt(0);
    if (type === "b") {
      return {
        type: "message",
        data: decodeBase64Packet(encodedPacket.substring(1), binaryType)
      };
    }
    const packetType = PACKET_TYPES_REVERSE[type];
    if (!packetType) {
      return ERROR_PACKET;
    }
    return encodedPacket.length > 1 ? {
      type: PACKET_TYPES_REVERSE[type],
      data: encodedPacket.substring(1)
    } : {
      type: PACKET_TYPES_REVERSE[type]
    };
  };
  var decodeBase64Packet = (data, binaryType) => {
    if (withNativeArrayBuffer2) {
      const decoded = decode(data);
      return mapBinary(decoded, binaryType);
    } else {
      return { base64: true, data };
    }
  };
  var mapBinary = (data, binaryType) => {
    switch (binaryType) {
      case "blob":
        if (data instanceof Blob) {
          return data;
        } else {
          return new Blob([data]);
        }
      case "arraybuffer":
      default:
        if (data instanceof ArrayBuffer) {
          return data;
        } else {
          return data.buffer;
        }
    }
  };

  // node_modules/engine.io-parser/build/esm/index.js
  var SEPARATOR = String.fromCharCode(30);
  var encodePayload = (packets, callback) => {
    const length = packets.length;
    const encodedPackets = new Array(length);
    let count = 0;
    packets.forEach((packet, i) => {
      encodePacket(packet, false, (encodedPacket) => {
        encodedPackets[i] = encodedPacket;
        if (++count === length) {
          callback(encodedPackets.join(SEPARATOR));
        }
      });
    });
  };
  var decodePayload = (encodedPayload, binaryType) => {
    const encodedPackets = encodedPayload.split(SEPARATOR);
    const packets = [];
    for (let i = 0; i < encodedPackets.length; i++) {
      const decodedPacket = decodePacket(encodedPackets[i], binaryType);
      packets.push(decodedPacket);
      if (decodedPacket.type === "error") {
        break;
      }
    }
    return packets;
  };
  function createPacketEncoderStream() {
    return new TransformStream({
      transform(packet, controller) {
        encodePacketToBinary(packet, (encodedPacket) => {
          const payloadLength = encodedPacket.length;
          let header;
          if (payloadLength < 126) {
            header = new Uint8Array(1);
            new DataView(header.buffer).setUint8(0, payloadLength);
          } else if (payloadLength < 65536) {
            header = new Uint8Array(3);
            const view = new DataView(header.buffer);
            view.setUint8(0, 126);
            view.setUint16(1, payloadLength);
          } else {
            header = new Uint8Array(9);
            const view = new DataView(header.buffer);
            view.setUint8(0, 127);
            view.setBigUint64(1, BigInt(payloadLength));
          }
          if (packet.data && typeof packet.data !== "string") {
            header[0] |= 128;
          }
          controller.enqueue(header);
          controller.enqueue(encodedPacket);
        });
      }
    });
  }
  var TEXT_DECODER;
  function totalLength(chunks) {
    return chunks.reduce((acc, chunk) => acc + chunk.length, 0);
  }
  function concatChunks(chunks, size) {
    if (chunks[0].length === size) {
      return chunks.shift();
    }
    const buffer = new Uint8Array(size);
    let j = 0;
    for (let i = 0; i < size; i++) {
      buffer[i] = chunks[0][j++];
      if (j === chunks[0].length) {
        chunks.shift();
        j = 0;
      }
    }
    if (chunks.length && j < chunks[0].length) {
      chunks[0] = chunks[0].slice(j);
    }
    return buffer;
  }
  function createPacketDecoderStream(maxPayload, binaryType) {
    if (!TEXT_DECODER) {
      TEXT_DECODER = new TextDecoder();
    }
    const chunks = [];
    let state = 0;
    let expectedLength = -1;
    let isBinary2 = false;
    return new TransformStream({
      transform(chunk, controller) {
        chunks.push(chunk);
        while (true) {
          if (state === 0) {
            if (totalLength(chunks) < 1) {
              break;
            }
            const header = concatChunks(chunks, 1);
            isBinary2 = (header[0] & 128) === 128;
            expectedLength = header[0] & 127;
            if (expectedLength < 126) {
              state = 3;
            } else if (expectedLength === 126) {
              state = 1;
            } else {
              state = 2;
            }
          } else if (state === 1) {
            if (totalLength(chunks) < 2) {
              break;
            }
            const headerArray = concatChunks(chunks, 2);
            expectedLength = new DataView(headerArray.buffer, headerArray.byteOffset, headerArray.length).getUint16(0);
            state = 3;
          } else if (state === 2) {
            if (totalLength(chunks) < 8) {
              break;
            }
            const headerArray = concatChunks(chunks, 8);
            const view = new DataView(headerArray.buffer, headerArray.byteOffset, headerArray.length);
            const n = view.getUint32(0);
            if (n > Math.pow(2, 53 - 32) - 1) {
              controller.enqueue(ERROR_PACKET);
              break;
            }
            expectedLength = n * Math.pow(2, 32) + view.getUint32(4);
            state = 3;
          } else {
            if (totalLength(chunks) < expectedLength) {
              break;
            }
            const data = concatChunks(chunks, expectedLength);
            controller.enqueue(decodePacket(isBinary2 ? data : TEXT_DECODER.decode(data), binaryType));
            state = 0;
          }
          if (expectedLength === 0 || expectedLength > maxPayload) {
            controller.enqueue(ERROR_PACKET);
            break;
          }
        }
      }
    });
  }
  var protocol = 4;

  // node_modules/@socket.io/component-emitter/lib/esm/index.js
  function Emitter(obj) {
    if (obj) return mixin(obj);
  }
  function mixin(obj) {
    for (var key in Emitter.prototype) {
      obj[key] = Emitter.prototype[key];
    }
    return obj;
  }
  Emitter.prototype.on = Emitter.prototype.addEventListener = function(event, fn) {
    this._callbacks = this._callbacks || {};
    (this._callbacks["$" + event] = this._callbacks["$" + event] || []).push(fn);
    return this;
  };
  Emitter.prototype.once = function(event, fn) {
    function on2() {
      this.off(event, on2);
      fn.apply(this, arguments);
    }
    on2.fn = fn;
    this.on(event, on2);
    return this;
  };
  Emitter.prototype.off = Emitter.prototype.removeListener = Emitter.prototype.removeAllListeners = Emitter.prototype.removeEventListener = function(event, fn) {
    this._callbacks = this._callbacks || {};
    if (0 == arguments.length) {
      this._callbacks = {};
      return this;
    }
    var callbacks = this._callbacks["$" + event];
    if (!callbacks) return this;
    if (1 == arguments.length) {
      delete this._callbacks["$" + event];
      return this;
    }
    var cb;
    for (var i = 0; i < callbacks.length; i++) {
      cb = callbacks[i];
      if (cb === fn || cb.fn === fn) {
        callbacks.splice(i, 1);
        break;
      }
    }
    if (callbacks.length === 0) {
      delete this._callbacks["$" + event];
    }
    return this;
  };
  Emitter.prototype.emit = function(event) {
    this._callbacks = this._callbacks || {};
    var args = new Array(arguments.length - 1), callbacks = this._callbacks["$" + event];
    for (var i = 1; i < arguments.length; i++) {
      args[i - 1] = arguments[i];
    }
    if (callbacks) {
      callbacks = callbacks.slice(0);
      for (var i = 0, len = callbacks.length; i < len; ++i) {
        callbacks[i].apply(this, args);
      }
    }
    return this;
  };
  Emitter.prototype.emitReserved = Emitter.prototype.emit;
  Emitter.prototype.listeners = function(event) {
    this._callbacks = this._callbacks || {};
    return this._callbacks["$" + event] || [];
  };
  Emitter.prototype.hasListeners = function(event) {
    return !!this.listeners(event).length;
  };

  // node_modules/engine.io-client/build/esm/globals.js
  var nextTick = (() => {
    const isPromiseAvailable = typeof Promise === "function" && typeof Promise.resolve === "function";
    if (isPromiseAvailable) {
      return (cb) => Promise.resolve().then(cb);
    } else {
      return (cb, setTimeoutFn) => setTimeoutFn(cb, 0);
    }
  })();
  var globalThisShim = (() => {
    if (typeof self !== "undefined") {
      return self;
    } else if (typeof window !== "undefined") {
      return window;
    } else {
      return Function("return this")();
    }
  })();
  var defaultBinaryType = "arraybuffer";
  function createCookieJar() {
  }

  // node_modules/engine.io-client/build/esm/util.js
  function pick(obj, ...attr) {
    return attr.reduce((acc, k) => {
      if (obj.hasOwnProperty(k)) {
        acc[k] = obj[k];
      }
      return acc;
    }, {});
  }
  var NATIVE_SET_TIMEOUT = globalThisShim.setTimeout;
  var NATIVE_CLEAR_TIMEOUT = globalThisShim.clearTimeout;
  function installTimerFunctions(obj, opts) {
    if (opts.useNativeTimers) {
      obj.setTimeoutFn = NATIVE_SET_TIMEOUT.bind(globalThisShim);
      obj.clearTimeoutFn = NATIVE_CLEAR_TIMEOUT.bind(globalThisShim);
    } else {
      obj.setTimeoutFn = globalThisShim.setTimeout.bind(globalThisShim);
      obj.clearTimeoutFn = globalThisShim.clearTimeout.bind(globalThisShim);
    }
  }
  var BASE64_OVERHEAD = 1.33;
  function byteLength(obj) {
    if (typeof obj === "string") {
      return utf8Length(obj);
    }
    return Math.ceil((obj.byteLength || obj.size) * BASE64_OVERHEAD);
  }
  function utf8Length(str) {
    let c = 0, length = 0;
    for (let i = 0, l = str.length; i < l; i++) {
      c = str.charCodeAt(i);
      if (c < 128) {
        length += 1;
      } else if (c < 2048) {
        length += 2;
      } else if (c < 55296 || c >= 57344) {
        length += 3;
      } else {
        i++;
        length += 4;
      }
    }
    return length;
  }
  function randomString() {
    return Date.now().toString(36).substring(3) + Math.random().toString(36).substring(2, 5);
  }

  // node_modules/engine.io-client/build/esm/contrib/parseqs.js
  function encode(obj) {
    let str = "";
    for (let i in obj) {
      if (obj.hasOwnProperty(i)) {
        if (str.length)
          str += "&";
        str += encodeURIComponent(i) + "=" + encodeURIComponent(obj[i]);
      }
    }
    return str;
  }
  function decode2(qs) {
    let qry = {};
    let pairs = qs.split("&");
    for (let i = 0, l = pairs.length; i < l; i++) {
      let pair = pairs[i].split("=");
      qry[decodeURIComponent(pair[0])] = decodeURIComponent(pair[1]);
    }
    return qry;
  }

  // node_modules/engine.io-client/build/esm/transport.js
  var TransportError = class extends Error {
    constructor(reason, description, context) {
      super(reason);
      this.description = description;
      this.context = context;
      this.type = "TransportError";
    }
  };
  var Transport = class extends Emitter {
    /**
     * Transport abstract constructor.
     *
     * @param {Object} opts - options
     * @protected
     */
    constructor(opts) {
      super();
      this.writable = false;
      installTimerFunctions(this, opts);
      this.opts = opts;
      this.query = opts.query;
      this.socket = opts.socket;
      this.supportsBinary = !opts.forceBase64;
    }
    /**
     * Emits an error.
     *
     * @param {String} reason
     * @param description
     * @param context - the error context
     * @return {Transport} for chaining
     * @protected
     */
    onError(reason, description, context) {
      super.emitReserved("error", new TransportError(reason, description, context));
      return this;
    }
    /**
     * Opens the transport.
     */
    open() {
      this.readyState = "opening";
      this.doOpen();
      return this;
    }
    /**
     * Closes the transport.
     */
    close() {
      if (this.readyState === "opening" || this.readyState === "open") {
        this.doClose();
        this.onClose();
      }
      return this;
    }
    /**
     * Sends multiple packets.
     *
     * @param {Array} packets
     */
    send(packets) {
      if (this.readyState === "open") {
        this.write(packets);
      } else {
      }
    }
    /**
     * Called upon open
     *
     * @protected
     */
    onOpen() {
      this.readyState = "open";
      this.writable = true;
      super.emitReserved("open");
    }
    /**
     * Called with data.
     *
     * @param {String} data
     * @protected
     */
    onData(data) {
      const packet = decodePacket(data, this.socket.binaryType);
      this.onPacket(packet);
    }
    /**
     * Called with a decoded packet.
     *
     * @protected
     */
    onPacket(packet) {
      super.emitReserved("packet", packet);
    }
    /**
     * Called upon close.
     *
     * @protected
     */
    onClose(details) {
      this.readyState = "closed";
      super.emitReserved("close", details);
    }
    /**
     * Pauses the transport, in order not to lose packets during an upgrade.
     *
     * @param onPause
     */
    pause(onPause) {
    }
    createUri(schema, query = {}) {
      return schema + "://" + this._hostname() + this._port() + this.opts.path + this._query(query);
    }
    _hostname() {
      const hostname = this.opts.hostname;
      return hostname.indexOf(":") === -1 ? hostname : "[" + hostname + "]";
    }
    _port() {
      if (this.opts.port && (this.opts.secure && Number(this.opts.port) !== 443 || !this.opts.secure && Number(this.opts.port) !== 80)) {
        return ":" + this.opts.port;
      } else {
        return "";
      }
    }
    _query(query) {
      const encodedQuery = encode(query);
      return encodedQuery.length ? "?" + encodedQuery : "";
    }
  };

  // node_modules/engine.io-client/build/esm/transports/polling.js
  var Polling = class extends Transport {
    constructor() {
      super(...arguments);
      this._polling = false;
    }
    get name() {
      return "polling";
    }
    /**
     * Opens the socket (triggers polling). We write a PING message to determine
     * when the transport is open.
     *
     * @protected
     */
    doOpen() {
      this._poll();
    }
    /**
     * Pauses polling.
     *
     * @param {Function} onPause - callback upon buffers are flushed and transport is paused
     * @package
     */
    pause(onPause) {
      this.readyState = "pausing";
      const pause = () => {
        this.readyState = "paused";
        onPause();
      };
      if (this._polling || !this.writable) {
        let total = 0;
        if (this._polling) {
          total++;
          this.once("pollComplete", function() {
            --total || pause();
          });
        }
        if (!this.writable) {
          total++;
          this.once("drain", function() {
            --total || pause();
          });
        }
      } else {
        pause();
      }
    }
    /**
     * Starts polling cycle.
     *
     * @private
     */
    _poll() {
      this._polling = true;
      this.doPoll();
      this.emitReserved("poll");
    }
    /**
     * Overloads onData to detect payloads.
     *
     * @protected
     */
    onData(data) {
      const callback = (packet) => {
        if ("opening" === this.readyState && packet.type === "open") {
          this.onOpen();
        }
        if ("close" === packet.type) {
          this.onClose({ description: "transport closed by the server" });
          return false;
        }
        this.onPacket(packet);
      };
      decodePayload(data, this.socket.binaryType).forEach(callback);
      if ("closed" !== this.readyState) {
        this._polling = false;
        this.emitReserved("pollComplete");
        if ("open" === this.readyState) {
          this._poll();
        } else {
        }
      }
    }
    /**
     * For polling, send a close packet.
     *
     * @protected
     */
    doClose() {
      const close = () => {
        this.write([{ type: "close" }]);
      };
      if ("open" === this.readyState) {
        close();
      } else {
        this.once("open", close);
      }
    }
    /**
     * Writes a packets payload.
     *
     * @param {Array} packets - data packets
     * @protected
     */
    write(packets) {
      this.writable = false;
      encodePayload(packets, (data) => {
        this.doWrite(data, () => {
          this.writable = true;
          this.emitReserved("drain");
        });
      });
    }
    /**
     * Generates uri for connection.
     *
     * @private
     */
    uri() {
      const schema = this.opts.secure ? "https" : "http";
      const query = this.query || {};
      if (false !== this.opts.timestampRequests) {
        query[this.opts.timestampParam] = randomString();
      }
      if (!this.supportsBinary && !query.sid) {
        query.b64 = 1;
      }
      return this.createUri(schema, query);
    }
  };

  // node_modules/engine.io-client/build/esm/contrib/has-cors.js
  var value = false;
  try {
    value = typeof XMLHttpRequest !== "undefined" && "withCredentials" in new XMLHttpRequest();
  } catch (err) {
  }
  var hasCORS = value;

  // node_modules/engine.io-client/build/esm/transports/polling-xhr.js
  function empty() {
  }
  var BaseXHR = class extends Polling {
    /**
     * XHR Polling constructor.
     *
     * @param {Object} opts
     * @package
     */
    constructor(opts) {
      super(opts);
      if (typeof location !== "undefined") {
        const isSSL = "https:" === location.protocol;
        let port = location.port;
        if (!port) {
          port = isSSL ? "443" : "80";
        }
        this.xd = typeof location !== "undefined" && opts.hostname !== location.hostname || port !== opts.port;
      }
    }
    /**
     * Sends data.
     *
     * @param {String} data - data to send.
     * @param {Function} fn - called upon flush.
     * @private
     */
    doWrite(data, fn) {
      const req = this.request({
        method: "POST",
        data
      });
      req.on("success", fn);
      req.on("error", (xhrStatus, context) => {
        this.onError("xhr post error", xhrStatus, context);
      });
    }
    /**
     * Starts a poll cycle.
     *
     * @private
     */
    doPoll() {
      const req = this.request();
      req.on("data", this.onData.bind(this));
      req.on("error", (xhrStatus, context) => {
        this.onError("xhr poll error", xhrStatus, context);
      });
      this.pollXhr = req;
    }
  };
  var Request = class _Request extends Emitter {
    /**
     * Request constructor
     *
     * @param {Object} options
     * @package
     */
    constructor(createRequest, uri, opts) {
      super();
      this.createRequest = createRequest;
      installTimerFunctions(this, opts);
      this._opts = opts;
      this._method = opts.method || "GET";
      this._uri = uri;
      this._data = void 0 !== opts.data ? opts.data : null;
      this._create();
    }
    /**
     * Creates the XHR object and sends the request.
     *
     * @private
     */
    _create() {
      var _a;
      const opts = pick(this._opts, "agent", "pfx", "key", "passphrase", "cert", "ca", "ciphers", "rejectUnauthorized", "autoUnref");
      opts.xdomain = !!this._opts.xd;
      const xhr = this._xhr = this.createRequest(opts);
      try {
        xhr.open(this._method, this._uri, true);
        try {
          if (this._opts.extraHeaders) {
            xhr.setDisableHeaderCheck && xhr.setDisableHeaderCheck(true);
            for (let i in this._opts.extraHeaders) {
              if (this._opts.extraHeaders.hasOwnProperty(i)) {
                xhr.setRequestHeader(i, this._opts.extraHeaders[i]);
              }
            }
          }
        } catch (e) {
        }
        if ("POST" === this._method) {
          try {
            xhr.setRequestHeader("Content-type", "text/plain;charset=UTF-8");
          } catch (e) {
          }
        }
        try {
          xhr.setRequestHeader("Accept", "*/*");
        } catch (e) {
        }
        (_a = this._opts.cookieJar) === null || _a === void 0 ? void 0 : _a.addCookies(xhr);
        if ("withCredentials" in xhr) {
          xhr.withCredentials = this._opts.withCredentials;
        }
        if (this._opts.requestTimeout) {
          xhr.timeout = this._opts.requestTimeout;
        }
        xhr.onreadystatechange = () => {
          var _a2;
          if (xhr.readyState === 3) {
            (_a2 = this._opts.cookieJar) === null || _a2 === void 0 ? void 0 : _a2.parseCookies(
              // @ts-ignore
              xhr.getResponseHeader("set-cookie")
            );
          }
          if (4 !== xhr.readyState)
            return;
          if (200 === xhr.status || 1223 === xhr.status) {
            this._onLoad();
          } else {
            this.setTimeoutFn(() => {
              this._onError(typeof xhr.status === "number" ? xhr.status : 0);
            }, 0);
          }
        };
        xhr.send(this._data);
      } catch (e) {
        this.setTimeoutFn(() => {
          this._onError(e);
        }, 0);
        return;
      }
      if (typeof document !== "undefined") {
        this._index = _Request.requestsCount++;
        _Request.requests[this._index] = this;
      }
    }
    /**
     * Called upon error.
     *
     * @private
     */
    _onError(err) {
      this.emitReserved("error", err, this._xhr);
      this._cleanup(true);
    }
    /**
     * Cleans up house.
     *
     * @private
     */
    _cleanup(fromError) {
      if ("undefined" === typeof this._xhr || null === this._xhr) {
        return;
      }
      this._xhr.onreadystatechange = empty;
      if (fromError) {
        try {
          this._xhr.abort();
        } catch (e) {
        }
      }
      if (typeof document !== "undefined") {
        delete _Request.requests[this._index];
      }
      this._xhr = null;
    }
    /**
     * Called upon load.
     *
     * @private
     */
    _onLoad() {
      const data = this._xhr.responseText;
      if (data !== null) {
        this.emitReserved("data", data);
        this.emitReserved("success");
        this._cleanup();
      }
    }
    /**
     * Aborts the request.
     *
     * @package
     */
    abort() {
      this._cleanup();
    }
  };
  Request.requestsCount = 0;
  Request.requests = {};
  if (typeof document !== "undefined") {
    if (typeof attachEvent === "function") {
      attachEvent("onunload", unloadHandler);
    } else if (typeof addEventListener === "function") {
      const terminationEvent = "onpagehide" in globalThisShim ? "pagehide" : "unload";
      addEventListener(terminationEvent, unloadHandler, false);
    }
  }
  function unloadHandler() {
    for (let i in Request.requests) {
      if (Request.requests.hasOwnProperty(i)) {
        Request.requests[i].abort();
      }
    }
  }
  var hasXHR2 = (function() {
    const xhr = newRequest({
      xdomain: false
    });
    return xhr && xhr.responseType !== null;
  })();
  var XHR = class extends BaseXHR {
    constructor(opts) {
      super(opts);
      const forceBase64 = opts && opts.forceBase64;
      this.supportsBinary = hasXHR2 && !forceBase64;
    }
    request(opts = {}) {
      Object.assign(opts, { xd: this.xd }, this.opts);
      return new Request(newRequest, this.uri(), opts);
    }
  };
  function newRequest(opts) {
    const xdomain = opts.xdomain;
    try {
      if ("undefined" !== typeof XMLHttpRequest && (!xdomain || hasCORS)) {
        return new XMLHttpRequest();
      }
    } catch (e) {
    }
    if (!xdomain) {
      try {
        return new globalThisShim[["Active"].concat("Object").join("X")]("Microsoft.XMLHTTP");
      } catch (e) {
      }
    }
  }

  // node_modules/engine.io-client/build/esm/transports/websocket.js
  var isReactNative = typeof navigator !== "undefined" && typeof navigator.product === "string" && navigator.product.toLowerCase() === "reactnative";
  var BaseWS = class extends Transport {
    get name() {
      return "websocket";
    }
    doOpen() {
      const uri = this.uri();
      const protocols = this.opts.protocols;
      const opts = isReactNative ? {} : pick(this.opts, "agent", "perMessageDeflate", "pfx", "key", "passphrase", "cert", "ca", "ciphers", "rejectUnauthorized", "localAddress", "protocolVersion", "origin", "maxPayload", "family", "checkServerIdentity");
      if (this.opts.extraHeaders) {
        opts.headers = this.opts.extraHeaders;
      }
      try {
        this.ws = this.createSocket(uri, protocols, opts);
      } catch (err) {
        return this.emitReserved("error", err);
      }
      this.ws.binaryType = this.socket.binaryType;
      this.addEventListeners();
    }
    /**
     * Adds event listeners to the socket
     *
     * @private
     */
    addEventListeners() {
      this.ws.onopen = () => {
        if (this.opts.autoUnref) {
          this.ws._socket.unref();
        }
        this.onOpen();
      };
      this.ws.onclose = (closeEvent) => this.onClose({
        description: "websocket connection closed",
        context: closeEvent
      });
      this.ws.onmessage = (ev) => this.onData(ev.data);
      this.ws.onerror = (e) => this.onError("websocket error", e);
    }
    write(packets) {
      this.writable = false;
      for (let i = 0; i < packets.length; i++) {
        const packet = packets[i];
        const lastPacket = i === packets.length - 1;
        encodePacket(packet, this.supportsBinary, (data) => {
          try {
            this.doWrite(packet, data);
          } catch (e) {
          }
          if (lastPacket) {
            nextTick(() => {
              this.writable = true;
              this.emitReserved("drain");
            }, this.setTimeoutFn);
          }
        });
      }
    }
    doClose() {
      if (typeof this.ws !== "undefined") {
        this.ws.onerror = () => {
        };
        this.ws.close();
        this.ws = null;
      }
    }
    /**
     * Generates uri for connection.
     *
     * @private
     */
    uri() {
      const schema = this.opts.secure ? "wss" : "ws";
      const query = this.query || {};
      if (this.opts.timestampRequests) {
        query[this.opts.timestampParam] = randomString();
      }
      if (!this.supportsBinary) {
        query.b64 = 1;
      }
      return this.createUri(schema, query);
    }
  };
  var WebSocketCtor = globalThisShim.WebSocket || globalThisShim.MozWebSocket;
  var WS = class extends BaseWS {
    createSocket(uri, protocols, opts) {
      return !isReactNative ? protocols ? new WebSocketCtor(uri, protocols) : new WebSocketCtor(uri) : new WebSocketCtor(uri, protocols, opts);
    }
    doWrite(_packet, data) {
      this.ws.send(data);
    }
  };

  // node_modules/engine.io-client/build/esm/transports/webtransport.js
  var WT = class extends Transport {
    get name() {
      return "webtransport";
    }
    doOpen() {
      try {
        this._transport = new WebTransport(this.createUri("https"), this.opts.transportOptions[this.name]);
      } catch (err) {
        return this.emitReserved("error", err);
      }
      this._transport.closed.then(() => {
        this.onClose();
      }).catch((err) => {
        this.onError("webtransport error", err);
      });
      this._transport.ready.then(() => {
        this._transport.createBidirectionalStream().then((stream) => {
          const decoderStream = createPacketDecoderStream(Number.MAX_SAFE_INTEGER, this.socket.binaryType);
          const reader = stream.readable.pipeThrough(decoderStream).getReader();
          const encoderStream = createPacketEncoderStream();
          encoderStream.readable.pipeTo(stream.writable);
          this._writer = encoderStream.writable.getWriter();
          const read = () => {
            reader.read().then(({ done, value: value2 }) => {
              if (done) {
                return;
              }
              this.onPacket(value2);
              read();
            }).catch((err) => {
            });
          };
          read();
          const packet = { type: "open" };
          if (this.query.sid) {
            packet.data = `{"sid":"${this.query.sid}"}`;
          }
          this._writer.write(packet).then(() => this.onOpen());
        });
      });
    }
    write(packets) {
      this.writable = false;
      for (let i = 0; i < packets.length; i++) {
        const packet = packets[i];
        const lastPacket = i === packets.length - 1;
        this._writer.write(packet).then(() => {
          if (lastPacket) {
            nextTick(() => {
              this.writable = true;
              this.emitReserved("drain");
            }, this.setTimeoutFn);
          }
        });
      }
    }
    doClose() {
      var _a;
      (_a = this._transport) === null || _a === void 0 ? void 0 : _a.close();
    }
  };

  // node_modules/engine.io-client/build/esm/transports/index.js
  var transports = {
    websocket: WS,
    webtransport: WT,
    polling: XHR
  };

  // node_modules/engine.io-client/build/esm/contrib/parseuri.js
  var re = /^(?:(?![^:@\/?#]+:[^:@\/]*@)(http|https|ws|wss):\/\/)?((?:(([^:@\/?#]*)(?::([^:@\/?#]*))?)?@)?((?:[a-f0-9]{0,4}:){2,7}[a-f0-9]{0,4}|[^:\/?#]*)(?::(\d*))?)(((\/(?:[^?#](?![^?#\/]*\.[^?#\/.]+(?:[?#]|$)))*\/?)?([^?#\/]*))(?:\?([^#]*))?(?:#(.*))?)/;
  var parts = [
    "source",
    "protocol",
    "authority",
    "userInfo",
    "user",
    "password",
    "host",
    "port",
    "relative",
    "path",
    "directory",
    "file",
    "query",
    "anchor"
  ];
  function parse(str) {
    if (str.length > 8e3) {
      throw "URI too long";
    }
    const src = str, b = str.indexOf("["), e = str.indexOf("]");
    if (b != -1 && e != -1) {
      str = str.substring(0, b) + str.substring(b, e).replace(/:/g, ";") + str.substring(e, str.length);
    }
    let m = re.exec(str || ""), uri = {}, i = 14;
    while (i--) {
      uri[parts[i]] = m[i] || "";
    }
    if (b != -1 && e != -1) {
      uri.source = src;
      uri.host = uri.host.substring(1, uri.host.length - 1).replace(/;/g, ":");
      uri.authority = uri.authority.replace("[", "").replace("]", "").replace(/;/g, ":");
      uri.ipv6uri = true;
    }
    uri.pathNames = pathNames(uri, uri["path"]);
    uri.queryKey = queryKey(uri, uri["query"]);
    return uri;
  }
  function pathNames(obj, path) {
    const regx = /\/{2,9}/g, names = path.replace(regx, "/").split("/");
    if (path.slice(0, 1) == "/" || path.length === 0) {
      names.splice(0, 1);
    }
    if (path.slice(-1) == "/") {
      names.splice(names.length - 1, 1);
    }
    return names;
  }
  function queryKey(uri, query) {
    const data = {};
    query.replace(/(?:^|&)([^&=]*)=?([^&]*)/g, function($0, $1, $2) {
      if ($1) {
        data[$1] = $2;
      }
    });
    return data;
  }

  // node_modules/engine.io-client/build/esm/socket.js
  var withEventListeners = typeof addEventListener === "function" && typeof removeEventListener === "function";
  var OFFLINE_EVENT_LISTENERS = [];
  if (withEventListeners) {
    addEventListener("offline", () => {
      OFFLINE_EVENT_LISTENERS.forEach((listener) => listener());
    }, false);
  }
  var SocketWithoutUpgrade = class _SocketWithoutUpgrade extends Emitter {
    /**
     * Socket constructor.
     *
     * @param {String|Object} uri - uri or options
     * @param {Object} opts - options
     */
    constructor(uri, opts) {
      super();
      this.binaryType = defaultBinaryType;
      this.writeBuffer = [];
      this._prevBufferLen = 0;
      this._pingInterval = -1;
      this._pingTimeout = -1;
      this._maxPayload = -1;
      this._pingTimeoutTime = Infinity;
      if (uri && "object" === typeof uri) {
        opts = uri;
        uri = null;
      }
      if (uri) {
        const parsedUri = parse(uri);
        opts.hostname = parsedUri.host;
        opts.secure = parsedUri.protocol === "https" || parsedUri.protocol === "wss";
        opts.port = parsedUri.port;
        if (parsedUri.query)
          opts.query = parsedUri.query;
      } else if (opts.host) {
        opts.hostname = parse(opts.host).host;
      }
      installTimerFunctions(this, opts);
      this.secure = null != opts.secure ? opts.secure : typeof location !== "undefined" && "https:" === location.protocol;
      if (opts.hostname && !opts.port) {
        opts.port = this.secure ? "443" : "80";
      }
      this.hostname = opts.hostname || (typeof location !== "undefined" ? location.hostname : "localhost");
      this.port = opts.port || (typeof location !== "undefined" && location.port ? location.port : this.secure ? "443" : "80");
      this.transports = [];
      this._transportsByName = {};
      opts.transports.forEach((t) => {
        const transportName = t.prototype.name;
        this.transports.push(transportName);
        this._transportsByName[transportName] = t;
      });
      this.opts = Object.assign({
        path: "/engine.io",
        agent: false,
        withCredentials: false,
        upgrade: true,
        timestampParam: "t",
        rememberUpgrade: false,
        addTrailingSlash: true,
        rejectUnauthorized: true,
        perMessageDeflate: {
          threshold: 1024
        },
        transportOptions: {},
        closeOnBeforeunload: false
      }, opts);
      this.opts.path = this.opts.path.replace(/\/$/, "") + (this.opts.addTrailingSlash ? "/" : "");
      if (typeof this.opts.query === "string") {
        this.opts.query = decode2(this.opts.query);
      }
      if (withEventListeners) {
        if (this.opts.closeOnBeforeunload) {
          this._beforeunloadEventListener = () => {
            if (this.transport) {
              this.transport.removeAllListeners();
              this.transport.close();
            }
          };
          addEventListener("beforeunload", this._beforeunloadEventListener, false);
        }
        if (this.hostname !== "localhost") {
          this._offlineEventListener = () => {
            this._onClose("transport close", {
              description: "network connection lost"
            });
          };
          OFFLINE_EVENT_LISTENERS.push(this._offlineEventListener);
        }
      }
      if (this.opts.withCredentials) {
        this._cookieJar = createCookieJar();
      }
      this._open();
    }
    /**
     * Creates transport of the given type.
     *
     * @param {String} name - transport name
     * @return {Transport}
     * @private
     */
    createTransport(name) {
      const query = Object.assign({}, this.opts.query);
      query.EIO = protocol;
      query.transport = name;
      if (this.id)
        query.sid = this.id;
      const opts = Object.assign({}, this.opts, {
        query,
        socket: this,
        hostname: this.hostname,
        secure: this.secure,
        port: this.port
      }, this.opts.transportOptions[name]);
      return new this._transportsByName[name](opts);
    }
    /**
     * Initializes transport to use and starts probe.
     *
     * @private
     */
    _open() {
      if (this.transports.length === 0) {
        this.setTimeoutFn(() => {
          this.emitReserved("error", "No transports available");
        }, 0);
        return;
      }
      const transportName = this.opts.rememberUpgrade && _SocketWithoutUpgrade.priorWebsocketSuccess && this.transports.indexOf("websocket") !== -1 ? "websocket" : this.transports[0];
      this.readyState = "opening";
      const transport = this.createTransport(transportName);
      transport.open();
      this.setTransport(transport);
    }
    /**
     * Sets the current transport. Disables the existing one (if any).
     *
     * @private
     */
    setTransport(transport) {
      if (this.transport) {
        this.transport.removeAllListeners();
      }
      this.transport = transport;
      transport.on("drain", this._onDrain.bind(this)).on("packet", this._onPacket.bind(this)).on("error", this._onError.bind(this)).on("close", (reason) => this._onClose("transport close", reason));
    }
    /**
     * Called when connection is deemed open.
     *
     * @private
     */
    onOpen() {
      this.readyState = "open";
      _SocketWithoutUpgrade.priorWebsocketSuccess = "websocket" === this.transport.name;
      this.emitReserved("open");
      this.flush();
    }
    /**
     * Handles a packet.
     *
     * @private
     */
    _onPacket(packet) {
      if ("opening" === this.readyState || "open" === this.readyState || "closing" === this.readyState) {
        this.emitReserved("packet", packet);
        this.emitReserved("heartbeat");
        switch (packet.type) {
          case "open":
            this.onHandshake(JSON.parse(packet.data));
            break;
          case "ping":
            this._sendPacket("pong");
            this.emitReserved("ping");
            this.emitReserved("pong");
            this._resetPingTimeout();
            break;
          case "error":
            const err = new Error("server error");
            err.code = packet.data;
            this._onError(err);
            break;
          case "message":
            this.emitReserved("data", packet.data);
            this.emitReserved("message", packet.data);
            break;
        }
      } else {
      }
    }
    /**
     * Called upon handshake completion.
     *
     * @param {Object} data - handshake obj
     * @private
     */
    onHandshake(data) {
      this.emitReserved("handshake", data);
      this.id = data.sid;
      this.transport.query.sid = data.sid;
      this._pingInterval = data.pingInterval;
      this._pingTimeout = data.pingTimeout;
      this._maxPayload = data.maxPayload;
      this.onOpen();
      if ("closed" === this.readyState)
        return;
      this._resetPingTimeout();
    }
    /**
     * Sets and resets ping timeout timer based on server pings.
     *
     * @private
     */
    _resetPingTimeout() {
      this.clearTimeoutFn(this._pingTimeoutTimer);
      const delay2 = this._pingInterval + this._pingTimeout;
      this._pingTimeoutTime = Date.now() + delay2;
      this._pingTimeoutTimer = this.setTimeoutFn(() => {
        this._onClose("ping timeout");
      }, delay2);
      if (this.opts.autoUnref) {
        this._pingTimeoutTimer.unref();
      }
    }
    /**
     * Called on `drain` event
     *
     * @private
     */
    _onDrain() {
      this.writeBuffer.splice(0, this._prevBufferLen);
      this._prevBufferLen = 0;
      if (0 === this.writeBuffer.length) {
        this.emitReserved("drain");
      } else {
        this.flush();
      }
    }
    /**
     * Flush write buffers.
     *
     * @private
     */
    flush() {
      if ("closed" !== this.readyState && this.transport.writable && !this.upgrading && this.writeBuffer.length) {
        const packets = this._getWritablePackets();
        this.transport.send(packets);
        this._prevBufferLen = packets.length;
        this.emitReserved("flush");
      }
    }
    /**
     * Ensure the encoded size of the writeBuffer is below the maxPayload value sent by the server (only for HTTP
     * long-polling)
     *
     * @private
     */
    _getWritablePackets() {
      const shouldCheckPayloadSize = this._maxPayload && this.transport.name === "polling" && this.writeBuffer.length > 1;
      if (!shouldCheckPayloadSize) {
        return this.writeBuffer;
      }
      let payloadSize = 1;
      for (let i = 0; i < this.writeBuffer.length; i++) {
        const data = this.writeBuffer[i].data;
        if (data) {
          payloadSize += byteLength(data);
        }
        if (i > 0 && payloadSize > this._maxPayload) {
          return this.writeBuffer.slice(0, i);
        }
        payloadSize += 2;
      }
      return this.writeBuffer;
    }
    /**
     * Checks whether the heartbeat timer has expired but the socket has not yet been notified.
     *
     * Note: this method is private for now because it does not really fit the WebSocket API, but if we put it in the
     * `write()` method then the message would not be buffered by the Socket.IO client.
     *
     * @return {boolean}
     * @private
     */
    /* private */
    _hasPingExpired() {
      if (!this._pingTimeoutTime)
        return true;
      const hasExpired = Date.now() > this._pingTimeoutTime;
      if (hasExpired) {
        this._pingTimeoutTime = 0;
        nextTick(() => {
          this._onClose("ping timeout");
        }, this.setTimeoutFn);
      }
      return hasExpired;
    }
    /**
     * Sends a message.
     *
     * @param {String} msg - message.
     * @param {Object} options.
     * @param {Function} fn - callback function.
     * @return {Socket} for chaining.
     */
    write(msg, options, fn) {
      this._sendPacket("message", msg, options, fn);
      return this;
    }
    /**
     * Sends a message. Alias of {@link Socket#write}.
     *
     * @param {String} msg - message.
     * @param {Object} options.
     * @param {Function} fn - callback function.
     * @return {Socket} for chaining.
     */
    send(msg, options, fn) {
      this._sendPacket("message", msg, options, fn);
      return this;
    }
    /**
     * Sends a packet.
     *
     * @param {String} type - packet type.
     * @param {String} data.
     * @param {Object} options.
     * @param {Function} fn - callback function.
     * @private
     */
    _sendPacket(type, data, options, fn) {
      if ("function" === typeof data) {
        fn = data;
        data = void 0;
      }
      if ("function" === typeof options) {
        fn = options;
        options = null;
      }
      if ("closing" === this.readyState || "closed" === this.readyState) {
        return;
      }
      options = options || {};
      options.compress = false !== options.compress;
      const packet = {
        type,
        data,
        options
      };
      this.emitReserved("packetCreate", packet);
      this.writeBuffer.push(packet);
      if (fn)
        this.once("flush", fn);
      this.flush();
    }
    /**
     * Closes the connection.
     */
    close() {
      const close = () => {
        this._onClose("forced close");
        this.transport.close();
      };
      const cleanupAndClose = () => {
        this.off("upgrade", cleanupAndClose);
        this.off("upgradeError", cleanupAndClose);
        close();
      };
      const waitForUpgrade = () => {
        this.once("upgrade", cleanupAndClose);
        this.once("upgradeError", cleanupAndClose);
      };
      if ("opening" === this.readyState || "open" === this.readyState) {
        this.readyState = "closing";
        if (this.writeBuffer.length) {
          this.once("drain", () => {
            if (this.upgrading) {
              waitForUpgrade();
            } else {
              close();
            }
          });
        } else if (this.upgrading) {
          waitForUpgrade();
        } else {
          close();
        }
      }
      return this;
    }
    /**
     * Called upon transport error
     *
     * @private
     */
    _onError(err) {
      _SocketWithoutUpgrade.priorWebsocketSuccess = false;
      if (this.opts.tryAllTransports && this.transports.length > 1 && this.readyState === "opening") {
        this.transports.shift();
        return this._open();
      }
      this.emitReserved("error", err);
      this._onClose("transport error", err);
    }
    /**
     * Called upon transport close.
     *
     * @private
     */
    _onClose(reason, description) {
      if ("opening" === this.readyState || "open" === this.readyState || "closing" === this.readyState) {
        this.clearTimeoutFn(this._pingTimeoutTimer);
        this.transport.removeAllListeners("close");
        this.transport.close();
        this.transport.removeAllListeners();
        if (withEventListeners) {
          if (this._beforeunloadEventListener) {
            removeEventListener("beforeunload", this._beforeunloadEventListener, false);
          }
          if (this._offlineEventListener) {
            const i = OFFLINE_EVENT_LISTENERS.indexOf(this._offlineEventListener);
            if (i !== -1) {
              OFFLINE_EVENT_LISTENERS.splice(i, 1);
            }
          }
        }
        this.readyState = "closed";
        this.id = null;
        this.emitReserved("close", reason, description);
        this.writeBuffer = [];
        this._prevBufferLen = 0;
      }
    }
  };
  SocketWithoutUpgrade.protocol = protocol;
  var SocketWithUpgrade = class extends SocketWithoutUpgrade {
    constructor() {
      super(...arguments);
      this._upgrades = [];
    }
    onOpen() {
      super.onOpen();
      if ("open" === this.readyState && this.opts.upgrade) {
        for (let i = 0; i < this._upgrades.length; i++) {
          this._probe(this._upgrades[i]);
        }
      }
    }
    /**
     * Probes a transport.
     *
     * @param {String} name - transport name
     * @private
     */
    _probe(name) {
      let transport = this.createTransport(name);
      let failed = false;
      SocketWithoutUpgrade.priorWebsocketSuccess = false;
      const onTransportOpen = () => {
        if (failed)
          return;
        transport.send([{ type: "ping", data: "probe" }]);
        transport.once("packet", (msg) => {
          if (failed)
            return;
          if ("pong" === msg.type && "probe" === msg.data) {
            this.upgrading = true;
            this.emitReserved("upgrading", transport);
            if (!transport)
              return;
            SocketWithoutUpgrade.priorWebsocketSuccess = "websocket" === transport.name;
            this.transport.pause(() => {
              if (failed)
                return;
              if ("closed" === this.readyState)
                return;
              cleanup();
              this.setTransport(transport);
              transport.send([{ type: "upgrade" }]);
              this.emitReserved("upgrade", transport);
              transport = null;
              this.upgrading = false;
              this.flush();
            });
          } else {
            const err = new Error("probe error");
            err.transport = transport.name;
            this.emitReserved("upgradeError", err);
          }
        });
      };
      function freezeTransport() {
        if (failed)
          return;
        failed = true;
        cleanup();
        transport.close();
        transport = null;
      }
      const onerror = (err) => {
        const error = new Error("probe error: " + err);
        error.transport = transport.name;
        freezeTransport();
        this.emitReserved("upgradeError", error);
      };
      function onTransportClose() {
        onerror("transport closed");
      }
      function onclose() {
        onerror("socket closed");
      }
      function onupgrade(to) {
        if (transport && to.name !== transport.name) {
          freezeTransport();
        }
      }
      const cleanup = () => {
        transport.removeListener("open", onTransportOpen);
        transport.removeListener("error", onerror);
        transport.removeListener("close", onTransportClose);
        this.off("close", onclose);
        this.off("upgrading", onupgrade);
      };
      transport.once("open", onTransportOpen);
      transport.once("error", onerror);
      transport.once("close", onTransportClose);
      this.once("close", onclose);
      this.once("upgrading", onupgrade);
      if (this._upgrades.indexOf("webtransport") !== -1 && name !== "webtransport") {
        this.setTimeoutFn(() => {
          if (!failed) {
            transport.open();
          }
        }, 200);
      } else {
        transport.open();
      }
    }
    onHandshake(data) {
      this._upgrades = this._filterUpgrades(data.upgrades);
      super.onHandshake(data);
    }
    /**
     * Filters upgrades, returning only those matching client transports.
     *
     * @param {Array} upgrades - server upgrades
     * @private
     */
    _filterUpgrades(upgrades) {
      const filteredUpgrades = [];
      for (let i = 0; i < upgrades.length; i++) {
        if (~this.transports.indexOf(upgrades[i]))
          filteredUpgrades.push(upgrades[i]);
      }
      return filteredUpgrades;
    }
  };
  var Socket = class extends SocketWithUpgrade {
    constructor(uri, opts = {}) {
      const isOptionsOnly = typeof uri === "object";
      const o = isOptionsOnly ? { ...uri } : { ...opts };
      if (!o.transports || o.transports && typeof o.transports[0] === "string") {
        o.transports = (o.transports || ["polling", "websocket", "webtransport"]).map((transportName) => transports[transportName]).filter((t) => !!t);
      }
      super(isOptionsOnly ? o : uri, o);
    }
  };

  // node_modules/engine.io-client/build/esm/index.js
  var protocol2 = Socket.protocol;

  // node_modules/socket.io-client/build/esm/url.js
  function url(uri, path = "", loc) {
    let obj = uri;
    loc = loc || typeof location !== "undefined" && location;
    if (null == uri)
      uri = loc.protocol + "//" + loc.host;
    if (typeof uri === "string") {
      if ("/" === uri.charAt(0)) {
        if ("/" === uri.charAt(1)) {
          uri = loc.protocol + uri;
        } else {
          uri = loc.host + uri;
        }
      }
      if (!/^(https?|wss?):\/\//.test(uri)) {
        if ("undefined" !== typeof loc) {
          uri = loc.protocol + "//" + uri;
        } else {
          uri = "https://" + uri;
        }
      }
      obj = parse(uri);
    }
    if (!obj.port) {
      if (/^(http|ws)$/.test(obj.protocol)) {
        obj.port = "80";
      } else if (/^(http|ws)s$/.test(obj.protocol)) {
        obj.port = "443";
      }
    }
    obj.path = obj.path || "/";
    const ipv6 = obj.host.indexOf(":") !== -1;
    const host = ipv6 ? "[" + obj.host + "]" : obj.host;
    obj.id = obj.protocol + "://" + host + ":" + obj.port + path;
    obj.href = obj.protocol + "://" + host + (loc && loc.port === obj.port ? "" : ":" + obj.port);
    return obj;
  }

  // node_modules/socket.io-parser/build/esm/index.js
  var esm_exports = {};
  __export(esm_exports, {
    Decoder: () => Decoder,
    Encoder: () => Encoder,
    PacketType: () => PacketType,
    isPacketValid: () => isPacketValid,
    protocol: () => protocol3
  });

  // node_modules/socket.io-parser/build/esm/is-binary.js
  var withNativeArrayBuffer3 = typeof ArrayBuffer === "function";
  var isView2 = (obj) => {
    return typeof ArrayBuffer.isView === "function" ? ArrayBuffer.isView(obj) : obj.buffer instanceof ArrayBuffer;
  };
  var toString = Object.prototype.toString;
  var withNativeBlob2 = typeof Blob === "function" || typeof Blob !== "undefined" && toString.call(Blob) === "[object BlobConstructor]";
  var withNativeFile = typeof File === "function" || typeof File !== "undefined" && toString.call(File) === "[object FileConstructor]";
  function isBinary(obj) {
    return withNativeArrayBuffer3 && (obj instanceof ArrayBuffer || isView2(obj)) || withNativeBlob2 && obj instanceof Blob || withNativeFile && obj instanceof File;
  }
  function hasBinary(obj, toJSON) {
    if (!obj || typeof obj !== "object") {
      return false;
    }
    if (Array.isArray(obj)) {
      for (let i = 0, l = obj.length; i < l; i++) {
        if (hasBinary(obj[i])) {
          return true;
        }
      }
      return false;
    }
    if (isBinary(obj)) {
      return true;
    }
    if (obj.toJSON && typeof obj.toJSON === "function" && arguments.length === 1) {
      return hasBinary(obj.toJSON(), true);
    }
    for (const key in obj) {
      if (Object.prototype.hasOwnProperty.call(obj, key) && hasBinary(obj[key])) {
        return true;
      }
    }
    return false;
  }

  // node_modules/socket.io-parser/build/esm/binary.js
  function deconstructPacket(packet) {
    const buffers = [];
    const packetData = packet.data;
    const pack = packet;
    pack.data = _deconstructPacket(packetData, buffers);
    pack.attachments = buffers.length;
    return { packet: pack, buffers };
  }
  function _deconstructPacket(data, buffers, toJSON) {
    if (!data)
      return data;
    if (isBinary(data)) {
      const placeholder = { _placeholder: true, num: buffers.length };
      buffers.push(data);
      return placeholder;
    } else if (Array.isArray(data)) {
      const newData = new Array(data.length);
      for (let i = 0; i < data.length; i++) {
        newData[i] = _deconstructPacket(data[i], buffers);
      }
      return newData;
    } else if (typeof data === "object" && !(data instanceof Date)) {
      if (data.toJSON && typeof data.toJSON === "function" && !toJSON) {
        return _deconstructPacket(data.toJSON(), buffers, true);
      }
      const newData = {};
      for (const key in data) {
        if (Object.prototype.hasOwnProperty.call(data, key)) {
          newData[key] = _deconstructPacket(data[key], buffers);
        }
      }
      return newData;
    }
    return data;
  }
  function reconstructPacket(packet, buffers) {
    packet.data = _reconstructPacket(packet.data, buffers);
    delete packet.attachments;
    return packet;
  }
  function _reconstructPacket(data, buffers) {
    if (!data)
      return data;
    if (data && data._placeholder === true) {
      const isIndexValid = typeof data.num === "number" && data.num >= 0 && data.num < buffers.length;
      if (isIndexValid) {
        return buffers[data.num];
      } else {
        throw new Error("illegal attachments");
      }
    } else if (Array.isArray(data)) {
      for (let i = 0; i < data.length; i++) {
        data[i] = _reconstructPacket(data[i], buffers);
      }
    } else if (typeof data === "object") {
      for (const key in data) {
        if (Object.prototype.hasOwnProperty.call(data, key)) {
          data[key] = _reconstructPacket(data[key], buffers);
        }
      }
    }
    return data;
  }

  // node_modules/socket.io-parser/build/esm/index.js
  var RESERVED_EVENTS = [
    "connect",
    // used on the client side
    "connect_error",
    // used on the client side
    "disconnect",
    // used on both sides
    "disconnecting",
    // used on the server side
    "newListener",
    // used by the Node.js EventEmitter
    "removeListener"
    // used by the Node.js EventEmitter
  ];
  var protocol3 = 5;
  var PacketType;
  (function(PacketType2) {
    PacketType2[PacketType2["CONNECT"] = 0] = "CONNECT";
    PacketType2[PacketType2["DISCONNECT"] = 1] = "DISCONNECT";
    PacketType2[PacketType2["EVENT"] = 2] = "EVENT";
    PacketType2[PacketType2["ACK"] = 3] = "ACK";
    PacketType2[PacketType2["CONNECT_ERROR"] = 4] = "CONNECT_ERROR";
    PacketType2[PacketType2["BINARY_EVENT"] = 5] = "BINARY_EVENT";
    PacketType2[PacketType2["BINARY_ACK"] = 6] = "BINARY_ACK";
  })(PacketType || (PacketType = {}));
  var Encoder = class {
    /**
     * Encoder constructor
     *
     * @param {function} replacer - custom replacer to pass down to JSON.parse
     */
    constructor(replacer) {
      this.replacer = replacer;
    }
    /**
     * Encode a packet as a single string if non-binary, or as a
     * buffer sequence, depending on packet type.
     *
     * @param {Object} obj - packet object
     */
    encode(obj) {
      if (obj.type === PacketType.EVENT || obj.type === PacketType.ACK) {
        if (hasBinary(obj)) {
          return this.encodeAsBinary({
            type: obj.type === PacketType.EVENT ? PacketType.BINARY_EVENT : PacketType.BINARY_ACK,
            nsp: obj.nsp,
            data: obj.data,
            id: obj.id
          });
        }
      }
      return [this.encodeAsString(obj)];
    }
    /**
     * Encode packet as string.
     */
    encodeAsString(obj) {
      let str = "" + obj.type;
      if (obj.type === PacketType.BINARY_EVENT || obj.type === PacketType.BINARY_ACK) {
        str += obj.attachments + "-";
      }
      if (obj.nsp && "/" !== obj.nsp) {
        str += obj.nsp + ",";
      }
      if (null != obj.id) {
        str += obj.id;
      }
      if (null != obj.data) {
        str += JSON.stringify(obj.data, this.replacer);
      }
      return str;
    }
    /**
     * Encode packet as 'buffer sequence' by removing blobs, and
     * deconstructing packet into object with placeholders and
     * a list of buffers.
     */
    encodeAsBinary(obj) {
      const deconstruction = deconstructPacket(obj);
      const pack = this.encodeAsString(deconstruction.packet);
      const buffers = deconstruction.buffers;
      buffers.unshift(pack);
      return buffers;
    }
  };
  var Decoder = class _Decoder extends Emitter {
    /**
     * Decoder constructor
     */
    constructor(opts) {
      super();
      this.opts = Object.assign({
        reviver: void 0,
        maxAttachments: 10
      }, typeof opts === "function" ? { reviver: opts } : opts);
    }
    /**
     * Decodes an encoded packet string into packet JSON.
     *
     * @param {String} obj - encoded packet
     */
    add(obj) {
      let packet;
      if (typeof obj === "string") {
        if (this.reconstructor) {
          throw new Error("got plaintext data when reconstructing a packet");
        }
        packet = this.decodeString(obj);
        const isBinaryEvent = packet.type === PacketType.BINARY_EVENT;
        if (isBinaryEvent || packet.type === PacketType.BINARY_ACK) {
          packet.type = isBinaryEvent ? PacketType.EVENT : PacketType.ACK;
          this.reconstructor = new BinaryReconstructor(packet);
        } else {
          super.emitReserved("decoded", packet);
        }
      } else if (isBinary(obj) || obj.base64) {
        if (!this.reconstructor) {
          throw new Error("got binary data when not reconstructing a packet");
        } else {
          packet = this.reconstructor.takeBinaryData(obj);
          if (packet) {
            this.reconstructor = null;
            super.emitReserved("decoded", packet);
          }
        }
      } else {
        throw new Error("Unknown type: " + obj);
      }
    }
    /**
     * Decode a packet String (JSON data)
     *
     * @param {String} str
     * @return {Object} packet
     */
    decodeString(str) {
      let i = 0;
      const p = {
        type: Number(str.charAt(0))
      };
      if (PacketType[p.type] === void 0) {
        throw new Error("unknown packet type " + p.type);
      }
      if (p.type === PacketType.BINARY_EVENT || p.type === PacketType.BINARY_ACK) {
        const start = i + 1;
        while (str.charAt(++i) !== "-" && i != str.length) {
        }
        const buf = str.substring(start, i);
        if (buf != Number(buf) || str.charAt(i) !== "-") {
          throw new Error("Illegal attachments");
        }
        const n = Number(buf);
        if (!isInteger(n) || n < 1) {
          throw new Error("Illegal attachments");
        } else if (n > this.opts.maxAttachments) {
          throw new Error("too many attachments");
        }
        p.attachments = n;
      }
      if ("/" === str.charAt(i + 1)) {
        const start = i + 1;
        while (++i) {
          const c = str.charAt(i);
          if ("," === c)
            break;
          if (i === str.length)
            break;
        }
        p.nsp = str.substring(start, i);
      } else {
        p.nsp = "/";
      }
      const next = str.charAt(i + 1);
      if ("" !== next && Number(next) == next) {
        const start = i + 1;
        while (++i) {
          const c = str.charAt(i);
          if (null == c || Number(c) != c) {
            --i;
            break;
          }
          if (i === str.length)
            break;
        }
        p.id = Number(str.substring(start, i + 1));
      }
      if (str.charAt(++i)) {
        const payload = this.tryParse(str.substr(i));
        if (_Decoder.isPayloadValid(p.type, payload)) {
          p.data = payload;
        } else {
          throw new Error("invalid payload");
        }
      }
      return p;
    }
    tryParse(str) {
      try {
        return JSON.parse(str, this.opts.reviver);
      } catch (e) {
        return false;
      }
    }
    static isPayloadValid(type, payload) {
      switch (type) {
        case PacketType.CONNECT:
          return isObject(payload);
        case PacketType.DISCONNECT:
          return payload === void 0;
        case PacketType.CONNECT_ERROR:
          return typeof payload === "string" || isObject(payload);
        case PacketType.EVENT:
        case PacketType.BINARY_EVENT:
          return Array.isArray(payload) && (typeof payload[0] === "number" || typeof payload[0] === "string" && RESERVED_EVENTS.indexOf(payload[0]) === -1);
        case PacketType.ACK:
        case PacketType.BINARY_ACK:
          return Array.isArray(payload);
      }
    }
    /**
     * Deallocates a parser's resources
     */
    destroy() {
      if (this.reconstructor) {
        this.reconstructor.finishedReconstruction();
        this.reconstructor = null;
      }
    }
  };
  var BinaryReconstructor = class {
    constructor(packet) {
      this.packet = packet;
      this.buffers = [];
      this.reconPack = packet;
    }
    /**
     * Method to be called when binary data received from connection
     * after a BINARY_EVENT packet.
     *
     * @param {Buffer | ArrayBuffer} binData - the raw binary data received
     * @return {null | Object} returns null if more binary data is expected or
     *   a reconstructed packet object if all buffers have been received.
     */
    takeBinaryData(binData) {
      this.buffers.push(binData);
      if (this.buffers.length === this.reconPack.attachments) {
        const packet = reconstructPacket(this.reconPack, this.buffers);
        this.finishedReconstruction();
        return packet;
      }
      return null;
    }
    /**
     * Cleans up binary packet reconstruction variables.
     */
    finishedReconstruction() {
      this.reconPack = null;
      this.buffers = [];
    }
  };
  function isNamespaceValid(nsp) {
    return typeof nsp === "string";
  }
  var isInteger = Number.isInteger || function(value2) {
    return typeof value2 === "number" && isFinite(value2) && Math.floor(value2) === value2;
  };
  function isAckIdValid(id) {
    return id === void 0 || isInteger(id);
  }
  function isObject(value2) {
    return Object.prototype.toString.call(value2) === "[object Object]";
  }
  function isDataValid(type, payload) {
    switch (type) {
      case PacketType.CONNECT:
        return payload === void 0 || isObject(payload);
      case PacketType.DISCONNECT:
        return payload === void 0;
      case PacketType.EVENT:
        return Array.isArray(payload) && (typeof payload[0] === "number" || typeof payload[0] === "string" && RESERVED_EVENTS.indexOf(payload[0]) === -1);
      case PacketType.ACK:
        return Array.isArray(payload);
      case PacketType.CONNECT_ERROR:
        return typeof payload === "string" || isObject(payload);
      default:
        return false;
    }
  }
  function isPacketValid(packet) {
    return isNamespaceValid(packet.nsp) && isAckIdValid(packet.id) && isDataValid(packet.type, packet.data);
  }

  // node_modules/socket.io-client/build/esm/on.js
  function on(obj, ev, fn) {
    obj.on(ev, fn);
    return function subDestroy() {
      obj.off(ev, fn);
    };
  }

  // node_modules/socket.io-client/build/esm/socket.js
  var RESERVED_EVENTS2 = Object.freeze({
    connect: 1,
    connect_error: 1,
    disconnect: 1,
    disconnecting: 1,
    // EventEmitter reserved events: https://nodejs.org/api/events.html#events_event_newlistener
    newListener: 1,
    removeListener: 1
  });
  var Socket2 = class extends Emitter {
    /**
     * `Socket` constructor.
     */
    constructor(io, nsp, opts) {
      super();
      this.connected = false;
      this.recovered = false;
      this.receiveBuffer = [];
      this.sendBuffer = [];
      this._queue = [];
      this._queueSeq = 0;
      this.ids = 0;
      this.acks = {};
      this.flags = {};
      this.io = io;
      this.nsp = nsp;
      if (opts && opts.auth) {
        this.auth = opts.auth;
      }
      this._opts = Object.assign({}, opts);
      if (this.io._autoConnect)
        this.open();
    }
    /**
     * Whether the socket is currently disconnected
     *
     * @example
     * const socket = io();
     *
     * socket.on("connect", () => {
     *   console.log(socket.disconnected); // false
     * });
     *
     * socket.on("disconnect", () => {
     *   console.log(socket.disconnected); // true
     * });
     */
    get disconnected() {
      return !this.connected;
    }
    /**
     * Subscribe to open, close and packet events
     *
     * @private
     */
    subEvents() {
      if (this.subs)
        return;
      const io = this.io;
      this.subs = [
        on(io, "open", this.onopen.bind(this)),
        on(io, "packet", this.onpacket.bind(this)),
        on(io, "error", this.onerror.bind(this)),
        on(io, "close", this.onclose.bind(this))
      ];
    }
    /**
     * Whether the Socket will try to reconnect when its Manager connects or reconnects.
     *
     * @example
     * const socket = io();
     *
     * console.log(socket.active); // true
     *
     * socket.on("disconnect", (reason) => {
     *   if (reason === "io server disconnect") {
     *     // the disconnection was initiated by the server, you need to manually reconnect
     *     console.log(socket.active); // false
     *   }
     *   // else the socket will automatically try to reconnect
     *   console.log(socket.active); // true
     * });
     */
    get active() {
      return !!this.subs;
    }
    /**
     * "Opens" the socket.
     *
     * @example
     * const socket = io({
     *   autoConnect: false
     * });
     *
     * socket.connect();
     */
    connect() {
      if (this.connected)
        return this;
      this.subEvents();
      if (!this.io["_reconnecting"])
        this.io.open();
      if ("open" === this.io._readyState)
        this.onopen();
      return this;
    }
    /**
     * Alias for {@link connect()}.
     */
    open() {
      return this.connect();
    }
    /**
     * Sends a `message` event.
     *
     * This method mimics the WebSocket.send() method.
     *
     * @see https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/send
     *
     * @example
     * socket.send("hello");
     *
     * // this is equivalent to
     * socket.emit("message", "hello");
     *
     * @return self
     */
    send(...args) {
      args.unshift("message");
      this.emit.apply(this, args);
      return this;
    }
    /**
     * Override `emit`.
     * If the event is in `events`, it's emitted normally.
     *
     * @example
     * socket.emit("hello", "world");
     *
     * // all serializable datastructures are supported (no need to call JSON.stringify)
     * socket.emit("hello", 1, "2", { 3: ["4"], 5: Uint8Array.from([6]) });
     *
     * // with an acknowledgement from the server
     * socket.emit("hello", "world", (val) => {
     *   // ...
     * });
     *
     * @return self
     */
    emit(ev, ...args) {
      var _a, _b, _c;
      if (RESERVED_EVENTS2.hasOwnProperty(ev)) {
        throw new Error('"' + ev.toString() + '" is a reserved event name');
      }
      args.unshift(ev);
      if (this._opts.retries && !this.flags.fromQueue && !this.flags.volatile) {
        this._addToQueue(args);
        return this;
      }
      const packet = {
        type: PacketType.EVENT,
        data: args
      };
      packet.options = {};
      packet.options.compress = this.flags.compress !== false;
      if ("function" === typeof args[args.length - 1]) {
        const id = this.ids++;
        const ack = args.pop();
        this._registerAckCallback(id, ack);
        packet.id = id;
      }
      const isTransportWritable = (_b = (_a = this.io.engine) === null || _a === void 0 ? void 0 : _a.transport) === null || _b === void 0 ? void 0 : _b.writable;
      const isConnected = this.connected && !((_c = this.io.engine) === null || _c === void 0 ? void 0 : _c._hasPingExpired());
      const discardPacket = this.flags.volatile && !isTransportWritable;
      if (discardPacket) {
      } else if (isConnected) {
        this.notifyOutgoingListeners(packet);
        this.packet(packet);
      } else {
        this.sendBuffer.push(packet);
      }
      this.flags = {};
      return this;
    }
    /**
     * @private
     */
    _registerAckCallback(id, ack) {
      var _a;
      const timeout = (_a = this.flags.timeout) !== null && _a !== void 0 ? _a : this._opts.ackTimeout;
      if (timeout === void 0) {
        this.acks[id] = ack;
        return;
      }
      const timer = this.io.setTimeoutFn(() => {
        delete this.acks[id];
        for (let i = 0; i < this.sendBuffer.length; i++) {
          if (this.sendBuffer[i].id === id) {
            this.sendBuffer.splice(i, 1);
          }
        }
        ack.call(this, new Error("operation has timed out"));
      }, timeout);
      const fn = (...args) => {
        this.io.clearTimeoutFn(timer);
        ack.apply(this, args);
      };
      fn.withError = true;
      this.acks[id] = fn;
    }
    /**
     * Emits an event and waits for an acknowledgement
     *
     * @example
     * // without timeout
     * const response = await socket.emitWithAck("hello", "world");
     *
     * // with a specific timeout
     * try {
     *   const response = await socket.timeout(1000).emitWithAck("hello", "world");
     * } catch (err) {
     *   // the server did not acknowledge the event in the given delay
     * }
     *
     * @return a Promise that will be fulfilled when the server acknowledges the event
     */
    emitWithAck(ev, ...args) {
      return new Promise((resolve, reject) => {
        const fn = (arg1, arg2) => {
          return arg1 ? reject(arg1) : resolve(arg2);
        };
        fn.withError = true;
        args.push(fn);
        this.emit(ev, ...args);
      });
    }
    /**
     * Add the packet to the queue.
     * @param args
     * @private
     */
    _addToQueue(args) {
      let ack;
      if (typeof args[args.length - 1] === "function") {
        ack = args.pop();
      }
      const packet = {
        id: this._queueSeq++,
        tryCount: 0,
        pending: false,
        args,
        flags: Object.assign({ fromQueue: true }, this.flags)
      };
      args.push((err, ...responseArgs) => {
        if (packet !== this._queue[0]) {
        }
        const hasError = err !== null;
        if (hasError) {
          if (packet.tryCount > this._opts.retries) {
            this._queue.shift();
            if (ack) {
              ack(err);
            }
          }
        } else {
          this._queue.shift();
          if (ack) {
            ack(null, ...responseArgs);
          }
        }
        packet.pending = false;
        return this._drainQueue();
      });
      this._queue.push(packet);
      this._drainQueue();
    }
    /**
     * Send the first packet of the queue, and wait for an acknowledgement from the server.
     * @param force - whether to resend a packet that has not been acknowledged yet
     *
     * @private
     */
    _drainQueue(force = false) {
      if (!this.connected || this._queue.length === 0) {
        return;
      }
      const packet = this._queue[0];
      if (packet.pending && !force) {
        return;
      }
      packet.pending = true;
      packet.tryCount++;
      this.flags = packet.flags;
      this.emit.apply(this, packet.args);
    }
    /**
     * Sends a packet.
     *
     * @param packet
     * @private
     */
    packet(packet) {
      packet.nsp = this.nsp;
      this.io._packet(packet);
    }
    /**
     * Called upon engine `open`.
     *
     * @private
     */
    onopen() {
      if (typeof this.auth == "function") {
        this.auth((data) => {
          this._sendConnectPacket(data);
        });
      } else {
        this._sendConnectPacket(this.auth);
      }
    }
    /**
     * Sends a CONNECT packet to initiate the Socket.IO session.
     *
     * @param data
     * @private
     */
    _sendConnectPacket(data) {
      this.packet({
        type: PacketType.CONNECT,
        data: this._pid ? Object.assign({ pid: this._pid, offset: this._lastOffset }, data) : data
      });
    }
    /**
     * Called upon engine or manager `error`.
     *
     * @param err
     * @private
     */
    onerror(err) {
      if (!this.connected) {
        this.emitReserved("connect_error", err);
      }
    }
    /**
     * Called upon engine `close`.
     *
     * @param reason
     * @param description
     * @private
     */
    onclose(reason, description) {
      this.connected = false;
      delete this.id;
      this.emitReserved("disconnect", reason, description);
      this._clearAcks();
    }
    /**
     * Clears the acknowledgement handlers upon disconnection, since the client will never receive an acknowledgement from
     * the server.
     *
     * @private
     */
    _clearAcks() {
      Object.keys(this.acks).forEach((id) => {
        const isBuffered = this.sendBuffer.some((packet) => String(packet.id) === id);
        if (!isBuffered) {
          const ack = this.acks[id];
          delete this.acks[id];
          if (ack.withError) {
            ack.call(this, new Error("socket has been disconnected"));
          }
        }
      });
    }
    /**
     * Called with socket packet.
     *
     * @param packet
     * @private
     */
    onpacket(packet) {
      const sameNamespace = packet.nsp === this.nsp;
      if (!sameNamespace)
        return;
      switch (packet.type) {
        case PacketType.CONNECT:
          if (packet.data && packet.data.sid) {
            this.onconnect(packet.data.sid, packet.data.pid);
          } else {
            this.emitReserved("connect_error", new Error("It seems you are trying to reach a Socket.IO server in v2.x with a v3.x client, but they are not compatible (more information here: https://socket.io/docs/v3/migrating-from-2-x-to-3-0/)"));
          }
          break;
        case PacketType.EVENT:
        case PacketType.BINARY_EVENT:
          this.onevent(packet);
          break;
        case PacketType.ACK:
        case PacketType.BINARY_ACK:
          this.onack(packet);
          break;
        case PacketType.DISCONNECT:
          this.ondisconnect();
          break;
        case PacketType.CONNECT_ERROR:
          this.destroy();
          const err = new Error(packet.data.message);
          err.data = packet.data.data;
          this.emitReserved("connect_error", err);
          break;
      }
    }
    /**
     * Called upon a server event.
     *
     * @param packet
     * @private
     */
    onevent(packet) {
      const args = packet.data || [];
      if (null != packet.id) {
        args.push(this.ack(packet.id));
      }
      if (this.connected) {
        this.emitEvent(args);
      } else {
        this.receiveBuffer.push(Object.freeze(args));
      }
    }
    emitEvent(args) {
      if (this._anyListeners && this._anyListeners.length) {
        const listeners = this._anyListeners.slice();
        for (const listener of listeners) {
          listener.apply(this, args);
        }
      }
      super.emit.apply(this, args);
      if (this._pid && args.length && typeof args[args.length - 1] === "string") {
        this._lastOffset = args[args.length - 1];
      }
    }
    /**
     * Produces an ack callback to emit with an event.
     *
     * @private
     */
    ack(id) {
      const self2 = this;
      let sent = false;
      return function(...args) {
        if (sent)
          return;
        sent = true;
        self2.packet({
          type: PacketType.ACK,
          id,
          data: args
        });
      };
    }
    /**
     * Called upon a server acknowledgement.
     *
     * @param packet
     * @private
     */
    onack(packet) {
      const ack = this.acks[packet.id];
      if (typeof ack !== "function") {
        return;
      }
      delete this.acks[packet.id];
      if (ack.withError) {
        packet.data.unshift(null);
      }
      ack.apply(this, packet.data);
    }
    /**
     * Called upon server connect.
     *
     * @private
     */
    onconnect(id, pid) {
      this.id = id;
      this.recovered = pid && this._pid === pid;
      this._pid = pid;
      this.connected = true;
      this.emitBuffered();
      this._drainQueue(true);
      this.emitReserved("connect");
    }
    /**
     * Emit buffered events (received and emitted).
     *
     * @private
     */
    emitBuffered() {
      this.receiveBuffer.forEach((args) => this.emitEvent(args));
      this.receiveBuffer = [];
      this.sendBuffer.forEach((packet) => {
        this.notifyOutgoingListeners(packet);
        this.packet(packet);
      });
      this.sendBuffer = [];
    }
    /**
     * Called upon server disconnect.
     *
     * @private
     */
    ondisconnect() {
      this.destroy();
      this.onclose("io server disconnect");
    }
    /**
     * Called upon forced client/server side disconnections,
     * this method ensures the manager stops tracking us and
     * that reconnections don't get triggered for this.
     *
     * @private
     */
    destroy() {
      if (this.subs) {
        this.subs.forEach((subDestroy) => subDestroy());
        this.subs = void 0;
      }
      this.io["_destroy"](this);
    }
    /**
     * Disconnects the socket manually. In that case, the socket will not try to reconnect.
     *
     * If this is the last active Socket instance of the {@link Manager}, the low-level connection will be closed.
     *
     * @example
     * const socket = io();
     *
     * socket.on("disconnect", (reason) => {
     *   // console.log(reason); prints "io client disconnect"
     * });
     *
     * socket.disconnect();
     *
     * @return self
     */
    disconnect() {
      if (this.connected) {
        this.packet({ type: PacketType.DISCONNECT });
      }
      this.destroy();
      if (this.connected) {
        this.onclose("io client disconnect");
      }
      return this;
    }
    /**
     * Alias for {@link disconnect()}.
     *
     * @return self
     */
    close() {
      return this.disconnect();
    }
    /**
     * Sets the compress flag.
     *
     * @example
     * socket.compress(false).emit("hello");
     *
     * @param compress - if `true`, compresses the sending data
     * @return self
     */
    compress(compress) {
      this.flags.compress = compress;
      return this;
    }
    /**
     * Sets a modifier for a subsequent event emission that the event message will be dropped when this socket is not
     * ready to send messages.
     *
     * @example
     * socket.volatile.emit("hello"); // the server may or may not receive it
     *
     * @returns self
     */
    get volatile() {
      this.flags.volatile = true;
      return this;
    }
    /**
     * Sets a modifier for a subsequent event emission that the callback will be called with an error when the
     * given number of milliseconds have elapsed without an acknowledgement from the server:
     *
     * @example
     * socket.timeout(5000).emit("my-event", (err) => {
     *   if (err) {
     *     // the server did not acknowledge the event in the given delay
     *   }
     * });
     *
     * @returns self
     */
    timeout(timeout) {
      this.flags.timeout = timeout;
      return this;
    }
    /**
     * Adds a listener that will be fired when any event is emitted. The event name is passed as the first argument to the
     * callback.
     *
     * @example
     * socket.onAny((event, ...args) => {
     *   console.log(`got ${event}`);
     * });
     *
     * @param listener
     */
    onAny(listener) {
      this._anyListeners = this._anyListeners || [];
      this._anyListeners.push(listener);
      return this;
    }
    /**
     * Adds a listener that will be fired when any event is emitted. The event name is passed as the first argument to the
     * callback. The listener is added to the beginning of the listeners array.
     *
     * @example
     * socket.prependAny((event, ...args) => {
     *   console.log(`got event ${event}`);
     * });
     *
     * @param listener
     */
    prependAny(listener) {
      this._anyListeners = this._anyListeners || [];
      this._anyListeners.unshift(listener);
      return this;
    }
    /**
     * Removes the listener that will be fired when any event is emitted.
     *
     * @example
     * const catchAllListener = (event, ...args) => {
     *   console.log(`got event ${event}`);
     * }
     *
     * socket.onAny(catchAllListener);
     *
     * // remove a specific listener
     * socket.offAny(catchAllListener);
     *
     * // or remove all listeners
     * socket.offAny();
     *
     * @param listener
     */
    offAny(listener) {
      if (!this._anyListeners) {
        return this;
      }
      if (listener) {
        const listeners = this._anyListeners;
        for (let i = 0; i < listeners.length; i++) {
          if (listener === listeners[i]) {
            listeners.splice(i, 1);
            return this;
          }
        }
      } else {
        this._anyListeners = [];
      }
      return this;
    }
    /**
     * Returns an array of listeners that are listening for any event that is specified. This array can be manipulated,
     * e.g. to remove listeners.
     */
    listenersAny() {
      return this._anyListeners || [];
    }
    /**
     * Adds a listener that will be fired when any event is emitted. The event name is passed as the first argument to the
     * callback.
     *
     * Note: acknowledgements sent to the server are not included.
     *
     * @example
     * socket.onAnyOutgoing((event, ...args) => {
     *   console.log(`sent event ${event}`);
     * });
     *
     * @param listener
     */
    onAnyOutgoing(listener) {
      this._anyOutgoingListeners = this._anyOutgoingListeners || [];
      this._anyOutgoingListeners.push(listener);
      return this;
    }
    /**
     * Adds a listener that will be fired when any event is emitted. The event name is passed as the first argument to the
     * callback. The listener is added to the beginning of the listeners array.
     *
     * Note: acknowledgements sent to the server are not included.
     *
     * @example
     * socket.prependAnyOutgoing((event, ...args) => {
     *   console.log(`sent event ${event}`);
     * });
     *
     * @param listener
     */
    prependAnyOutgoing(listener) {
      this._anyOutgoingListeners = this._anyOutgoingListeners || [];
      this._anyOutgoingListeners.unshift(listener);
      return this;
    }
    /**
     * Removes the listener that will be fired when any event is emitted.
     *
     * @example
     * const catchAllListener = (event, ...args) => {
     *   console.log(`sent event ${event}`);
     * }
     *
     * socket.onAnyOutgoing(catchAllListener);
     *
     * // remove a specific listener
     * socket.offAnyOutgoing(catchAllListener);
     *
     * // or remove all listeners
     * socket.offAnyOutgoing();
     *
     * @param [listener] - the catch-all listener (optional)
     */
    offAnyOutgoing(listener) {
      if (!this._anyOutgoingListeners) {
        return this;
      }
      if (listener) {
        const listeners = this._anyOutgoingListeners;
        for (let i = 0; i < listeners.length; i++) {
          if (listener === listeners[i]) {
            listeners.splice(i, 1);
            return this;
          }
        }
      } else {
        this._anyOutgoingListeners = [];
      }
      return this;
    }
    /**
     * Returns an array of listeners that are listening for any event that is specified. This array can be manipulated,
     * e.g. to remove listeners.
     */
    listenersAnyOutgoing() {
      return this._anyOutgoingListeners || [];
    }
    /**
     * Notify the listeners for each packet sent
     *
     * @param packet
     *
     * @private
     */
    notifyOutgoingListeners(packet) {
      if (this._anyOutgoingListeners && this._anyOutgoingListeners.length) {
        const listeners = this._anyOutgoingListeners.slice();
        for (const listener of listeners) {
          listener.apply(this, packet.data);
        }
      }
    }
  };

  // node_modules/socket.io-client/build/esm/contrib/backo2.js
  function Backoff(opts) {
    opts = opts || {};
    this.ms = opts.min || 100;
    this.max = opts.max || 1e4;
    this.factor = opts.factor || 2;
    this.jitter = opts.jitter > 0 && opts.jitter <= 1 ? opts.jitter : 0;
    this.attempts = 0;
  }
  Backoff.prototype.duration = function() {
    var ms = this.ms * Math.pow(this.factor, this.attempts++);
    if (this.jitter) {
      var rand = Math.random();
      var deviation = Math.floor(rand * this.jitter * ms);
      ms = (Math.floor(rand * 10) & 1) == 0 ? ms - deviation : ms + deviation;
    }
    return Math.min(ms, this.max) | 0;
  };
  Backoff.prototype.reset = function() {
    this.attempts = 0;
  };
  Backoff.prototype.setMin = function(min) {
    this.ms = min;
  };
  Backoff.prototype.setMax = function(max) {
    this.max = max;
  };
  Backoff.prototype.setJitter = function(jitter) {
    this.jitter = jitter;
  };

  // node_modules/socket.io-client/build/esm/manager.js
  var Manager = class extends Emitter {
    constructor(uri, opts) {
      var _a;
      super();
      this.nsps = {};
      this.subs = [];
      if (uri && "object" === typeof uri) {
        opts = uri;
        uri = void 0;
      }
      opts = opts || {};
      opts.path = opts.path || "/socket.io";
      this.opts = opts;
      installTimerFunctions(this, opts);
      this.reconnection(opts.reconnection !== false);
      this.reconnectionAttempts(opts.reconnectionAttempts || Infinity);
      this.reconnectionDelay(opts.reconnectionDelay || 1e3);
      this.reconnectionDelayMax(opts.reconnectionDelayMax || 5e3);
      this.randomizationFactor((_a = opts.randomizationFactor) !== null && _a !== void 0 ? _a : 0.5);
      this.backoff = new Backoff({
        min: this.reconnectionDelay(),
        max: this.reconnectionDelayMax(),
        jitter: this.randomizationFactor()
      });
      this.timeout(null == opts.timeout ? 2e4 : opts.timeout);
      this._readyState = "closed";
      this.uri = uri;
      const _parser = opts.parser || esm_exports;
      this.encoder = new _parser.Encoder();
      this.decoder = new _parser.Decoder();
      this._autoConnect = opts.autoConnect !== false;
      if (this._autoConnect)
        this.open();
    }
    reconnection(v) {
      if (!arguments.length)
        return this._reconnection;
      this._reconnection = !!v;
      if (!v) {
        this.skipReconnect = true;
      }
      return this;
    }
    reconnectionAttempts(v) {
      if (v === void 0)
        return this._reconnectionAttempts;
      this._reconnectionAttempts = v;
      return this;
    }
    reconnectionDelay(v) {
      var _a;
      if (v === void 0)
        return this._reconnectionDelay;
      this._reconnectionDelay = v;
      (_a = this.backoff) === null || _a === void 0 ? void 0 : _a.setMin(v);
      return this;
    }
    randomizationFactor(v) {
      var _a;
      if (v === void 0)
        return this._randomizationFactor;
      this._randomizationFactor = v;
      (_a = this.backoff) === null || _a === void 0 ? void 0 : _a.setJitter(v);
      return this;
    }
    reconnectionDelayMax(v) {
      var _a;
      if (v === void 0)
        return this._reconnectionDelayMax;
      this._reconnectionDelayMax = v;
      (_a = this.backoff) === null || _a === void 0 ? void 0 : _a.setMax(v);
      return this;
    }
    timeout(v) {
      if (!arguments.length)
        return this._timeout;
      this._timeout = v;
      return this;
    }
    /**
     * Starts trying to reconnect if reconnection is enabled and we have not
     * started reconnecting yet
     *
     * @private
     */
    maybeReconnectOnOpen() {
      if (!this._reconnecting && this._reconnection && this.backoff.attempts === 0) {
        this.reconnect();
      }
    }
    /**
     * Sets the current transport `socket`.
     *
     * @param {Function} fn - optional, callback
     * @return self
     * @public
     */
    open(fn) {
      if (~this._readyState.indexOf("open"))
        return this;
      this.engine = new Socket(this.uri, this.opts);
      const socket2 = this.engine;
      const self2 = this;
      this._readyState = "opening";
      this.skipReconnect = false;
      const openSubDestroy = on(socket2, "open", function() {
        self2.onopen();
        fn && fn();
      });
      const onError = (err) => {
        this.cleanup();
        this._readyState = "closed";
        this.emitReserved("error", err);
        if (fn) {
          fn(err);
        } else {
          this.maybeReconnectOnOpen();
        }
      };
      const errorSub = on(socket2, "error", onError);
      if (false !== this._timeout) {
        const timeout = this._timeout;
        const timer = this.setTimeoutFn(() => {
          openSubDestroy();
          onError(new Error("timeout"));
          socket2.close();
        }, timeout);
        if (this.opts.autoUnref) {
          timer.unref();
        }
        this.subs.push(() => {
          this.clearTimeoutFn(timer);
        });
      }
      this.subs.push(openSubDestroy);
      this.subs.push(errorSub);
      return this;
    }
    /**
     * Alias for open()
     *
     * @return self
     * @public
     */
    connect(fn) {
      return this.open(fn);
    }
    /**
     * Called upon transport open.
     *
     * @private
     */
    onopen() {
      this.cleanup();
      this._readyState = "open";
      this.emitReserved("open");
      const socket2 = this.engine;
      this.subs.push(
        on(socket2, "ping", this.onping.bind(this)),
        on(socket2, "data", this.ondata.bind(this)),
        on(socket2, "error", this.onerror.bind(this)),
        on(socket2, "close", this.onclose.bind(this)),
        // @ts-ignore
        on(this.decoder, "decoded", this.ondecoded.bind(this))
      );
    }
    /**
     * Called upon a ping.
     *
     * @private
     */
    onping() {
      this.emitReserved("ping");
    }
    /**
     * Called with data.
     *
     * @private
     */
    ondata(data) {
      try {
        this.decoder.add(data);
      } catch (e) {
        this.onclose("parse error", e);
      }
    }
    /**
     * Called when parser fully decodes a packet.
     *
     * @private
     */
    ondecoded(packet) {
      nextTick(() => {
        this.emitReserved("packet", packet);
      }, this.setTimeoutFn);
    }
    /**
     * Called upon socket error.
     *
     * @private
     */
    onerror(err) {
      this.emitReserved("error", err);
    }
    /**
     * Creates a new socket for the given `nsp`.
     *
     * @return {Socket}
     * @public
     */
    socket(nsp, opts) {
      let socket2 = this.nsps[nsp];
      if (!socket2) {
        socket2 = new Socket2(this, nsp, opts);
        this.nsps[nsp] = socket2;
      } else if (this._autoConnect && !socket2.active) {
        socket2.connect();
      }
      return socket2;
    }
    /**
     * Called upon a socket close.
     *
     * @param socket
     * @private
     */
    _destroy(socket2) {
      const nsps = Object.keys(this.nsps);
      for (const nsp of nsps) {
        const socket3 = this.nsps[nsp];
        if (socket3.active) {
          return;
        }
      }
      this._close();
    }
    /**
     * Writes a packet.
     *
     * @param packet
     * @private
     */
    _packet(packet) {
      const encodedPackets = this.encoder.encode(packet);
      for (let i = 0; i < encodedPackets.length; i++) {
        this.engine.write(encodedPackets[i], packet.options);
      }
    }
    /**
     * Clean up transport subscriptions and packet buffer.
     *
     * @private
     */
    cleanup() {
      this.subs.forEach((subDestroy) => subDestroy());
      this.subs.length = 0;
      this.decoder.destroy();
    }
    /**
     * Close the current socket.
     *
     * @private
     */
    _close() {
      this.skipReconnect = true;
      this._reconnecting = false;
      this.onclose("forced close");
    }
    /**
     * Alias for close()
     *
     * @private
     */
    disconnect() {
      return this._close();
    }
    /**
     * Called when:
     *
     * - the low-level engine is closed
     * - the parser encountered a badly formatted packet
     * - all sockets are disconnected
     *
     * @private
     */
    onclose(reason, description) {
      var _a;
      this.cleanup();
      (_a = this.engine) === null || _a === void 0 ? void 0 : _a.close();
      this.backoff.reset();
      this._readyState = "closed";
      this.emitReserved("close", reason, description);
      if (this._reconnection && !this.skipReconnect) {
        this.reconnect();
      }
    }
    /**
     * Attempt a reconnection.
     *
     * @private
     */
    reconnect() {
      if (this._reconnecting || this.skipReconnect)
        return this;
      const self2 = this;
      if (this.backoff.attempts >= this._reconnectionAttempts) {
        this.backoff.reset();
        this.emitReserved("reconnect_failed");
        this._reconnecting = false;
      } else {
        const delay2 = this.backoff.duration();
        this._reconnecting = true;
        const timer = this.setTimeoutFn(() => {
          if (self2.skipReconnect)
            return;
          this.emitReserved("reconnect_attempt", self2.backoff.attempts);
          if (self2.skipReconnect)
            return;
          self2.open((err) => {
            if (err) {
              self2._reconnecting = false;
              self2.reconnect();
              this.emitReserved("reconnect_error", err);
            } else {
              self2.onreconnect();
            }
          });
        }, delay2);
        if (this.opts.autoUnref) {
          timer.unref();
        }
        this.subs.push(() => {
          this.clearTimeoutFn(timer);
        });
      }
    }
    /**
     * Called upon successful reconnect.
     *
     * @private
     */
    onreconnect() {
      const attempt = this.backoff.attempts;
      this._reconnecting = false;
      this.backoff.reset();
      this.emitReserved("reconnect", attempt);
    }
  };

  // node_modules/socket.io-client/build/esm/index.js
  var cache = {};
  function lookup2(uri, opts) {
    if (typeof uri === "object") {
      opts = uri;
      uri = void 0;
    }
    opts = opts || {};
    const parsed = url(uri, opts.path || "/socket.io");
    const source = parsed.source;
    const id = parsed.id;
    const path = parsed.path;
    const sameNamespace = cache[id] && path in cache[id]["nsps"];
    const newConnection = opts.forceNew || opts["force new connection"] || false === opts.multiplex || sameNamespace;
    let io;
    if (newConnection) {
      io = new Manager(source, opts);
    } else {
      if (!cache[id]) {
        cache[id] = new Manager(source, opts);
      }
      io = cache[id];
    }
    if (parsed.query && !opts.query) {
      opts.query = parsed.queryKey;
    }
    return io.socket(parsed.path, opts);
  }
  Object.assign(lookup2, {
    Manager,
    Socket: Socket2,
    io: lookup2,
    connect: lookup2
  });

  // src/job-config.mjs
  var LIST_FIELDS = /* @__PURE__ */ new Set([
    "states",
    "rtos",
    "categoryGroups",
    "fuels",
    "archivedFlags",
    "financialYears",
    "emissions",
    "makers",
    "subCategories",
    "classes",
    "evTypes",
    "statuses",
    "ownerTypes"
  ]);
  function normalizeJobFilters(filters = {}) {
    return Object.fromEntries(Object.entries(filters).map(([key, value2]) => {
      if (LIST_FIELDS.has(key) && Array.isArray(value2)) {
        return [key, value2.map((item) => String(item).trim()).filter(Boolean).join(",")];
      }
      return [key, value2];
    }));
  }

  // src/report-upload.mjs
  async function uploadCapturedReport({
    serverUrl,
    jobId,
    runnerId,
    token,
    blob,
    fileName,
    signal,
    fetchImpl = fetch,
    attempts = 3,
    timeoutMs = 15e3,
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
  }) {
    let lastError;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      signal?.throwIfAborted();
      const controller = new AbortController();
      const cancel = () => controller.abort(signal.reason);
      signal?.addEventListener("abort", cancel, { once: true });
      const timer = setTimeout(() => controller.abort(new Error("Upload timed out.")), timeoutMs);
      let retryable = true;
      try {
        const body = new FormData();
        body.append("file", blob, fileName);
        const response = await fetchImpl(`${serverUrl.replace(/\/$/, "")}/api/jobs/${jobId}/upload-excel`, {
          method: "POST",
          headers: { "X-VAHAN-RUNNER-TOKEN": token, "X-VAHAN-RUNNER-ID": runnerId },
          body,
          signal: controller.signal
        });
        retryable = response.status >= 500 || response.status === 408 || response.status === 429;
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${result.detail || "Backend could not save Excel."}`);
        retryable = true;
        if (!result.ok || !result.fileName || result.sizeBytes !== blob.size) {
          throw new Error("Backend did not confirm the captured workbook's filename and byte size.");
        }
        signal?.throwIfAborted();
        return result;
      } catch (error) {
        signal?.throwIfAborted();
        lastError = error;
        if (!retryable) break;
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener("abort", cancel);
      }
      if (attempt < attempts - 1) await sleep(300 * (attempt + 1));
    }
    throw new Error(`EXCEL_UPLOAD_FAILED: ${lastError?.message || "Upload failed."} (${serverUrl})`);
  }
  function matchesReportCapture(message, sender, pending) {
    return Boolean(pending && sender.tab?.id === pending.tabId && message.captureId === pending.captureId);
  }
  function matchesJobPageResult(message, sender, job) {
    return Boolean(job && message.jobId === job.jobId && sender.tab?.id === job.tabId);
  }

  // src/vahan-auth-guard.mjs
  var VAHAN_AUTH_HOLD_KEY = "vahanAuthHold";
  var VAHAN_AUTH_REQUIRED_CODE = "VAHAN_AUTH_REQUIRED";
  var VAHAN_SESSION_EXPIRED_CODE = "VAHAN_SESSION_EXPIRED";
  var VAHAN_UNREACHABLE_CODE = "VAHAN_UNREACHABLE";
  var VAHAN_SERVER_ERROR_CODE = "VAHAN_SERVER_ERROR";
  var VAHAN_AUTH_HOLD_MS = 15 * 60 * 1e3;
  var VAHAN_AUTH_GUARD_VERSION = 2;
  var VAHAN_HOST = "analytics.parivahan.gov.in";
  function isVahanRequestUrl(value2) {
    try {
      const url2 = new URL(String(value2 || ""));
      return url2.protocol === "https:" && url2.hostname === VAHAN_HOST;
    } catch {
      return false;
    }
  }
  function isVahanPublicReportUrl(value2) {
    try {
      const url2 = new URL(String(value2 || ""));
      return url2.protocol === "https:" && url2.hostname === VAHAN_HOST && url2.pathname.startsWith("/analytics/vahanpublicreport");
    } catch {
      return false;
    }
  }
  function isVahanRedirectedHomeUrl(value2) {
    try {
      const url2 = new URL(String(value2 || ""));
      if (url2.hostname !== VAHAN_HOST) return false;
      const path = url2.pathname.replace(/\/+$/, "") || "/";
      return path === "" || path === "/" || path === "/analytics" || path === "/analytics/login";
    } catch {
      return false;
    }
  }
  function isChromeErrorUrl(value2) {
    const str = String(value2 || "").toLowerCase();
    return str.startsWith("chrome-error://") || str.startsWith("chrome-extension://") && str.includes("error") || str.includes("chromewebdata");
  }
  function isVahanMainFrameAuthChallenge(details = {}) {
    return details.isProxy !== true && details.type === "main_frame" && isVahanRequestUrl(details.url);
  }
  function safeUrl(value2) {
    try {
      const url2 = new URL(String(value2 || ""));
      return `${url2.origin}${url2.pathname}`;
    } catch {
      return `https://${VAHAN_HOST}/`;
    }
  }
  function timestamp(value2) {
    return new Date(value2).toISOString();
  }
  function createVahanAuthHold(details = {}, previous = null, now2 = Date.now()) {
    const tabId = Number.isInteger(details.tabId) && details.tabId >= 0 ? details.tabId : null;
    const sameChallenge = previous && previous.tabId === tabId && previous.code === VAHAN_AUTH_REQUIRED_CODE && Date.parse(previous.lastDetectedAt || "") > now2 - VAHAN_AUTH_HOLD_MS;
    return {
      guardVersion: VAHAN_AUTH_GUARD_VERSION,
      code: VAHAN_AUTH_REQUIRED_CODE,
      status: "AUTH_REQUIRED",
      host: VAHAN_HOST,
      resourceType: String(details.type || "unknown"),
      tabId,
      url: safeUrl(details.url),
      scheme: String(details.scheme || "Basic"),
      realm: String(details.realm || "").slice(0, 120),
      statusCode: Number(details.statusCode) || 401,
      occurrences: sameChallenge ? Number(previous.occurrences || 0) + 1 : 1,
      firstDetectedAt: sameChallenge ? previous.firstDetectedAt : timestamp(now2),
      lastDetectedAt: timestamp(now2),
      retryAfter: timestamp(now2 + VAHAN_AUTH_HOLD_MS)
    };
  }
  function isVahanAuthHoldActive(hold, now2 = Date.now(), tabId) {
    if (!hold || hold.guardVersion !== VAHAN_AUTH_GUARD_VERSION || hold.code !== VAHAN_AUTH_REQUIRED_CODE) return false;
    if (tabId !== void 0 && hold.tabId !== null && hold.tabId !== tabId) return false;
    const retryAfter = Date.parse(hold.retryAfter || "");
    return Number.isFinite(retryAfter) && retryAfter > now2;
  }
  function vahanAuthHoldMessage(hold = {}) {
    const retryAfter = hold.retryAfter ? new Date(hold.retryAfter).toLocaleString("en-GB") : "after confirmation";
    return `VAHAN requires HTTP authentication (${hold.statusCode || 401}). The extension is paused to prevent repeated retries. Close the sign-in dialog, wait until ${retryAfter}, verify that the official page is accessible, then try again.`;
  }
  function vahanSessionExpiredMessage() {
    return "The VAHAN session has expired (session timeout). Reload the VAHAN page to start a new session.";
  }
  function vahanUnreachableMessage(detail = "") {
    const reason = detail ? ` (${detail})` : "";
    return `Cannot reach VAHAN${reason}. The server may be under maintenance or your network may be disconnected.`;
  }

  // ui-drift/health-check.mjs
  var UI_HEALTH_CHECK_ALARM = "vahan-ui-health-check";
  var DEFAULT_UI_HEALTH_CHECK_INTERVAL_DAYS = 3;
  var MIN_UI_HEALTH_CHECK_INTERVAL_DAYS = 1;
  var MAX_UI_HEALTH_CHECK_INTERVAL_DAYS = 365;
  var UI_HEALTH_CHECK_INTERVAL_DAYS = DEFAULT_UI_HEALTH_CHECK_INTERVAL_DAYS;
  var UI_HEALTH_CHECK_INTERVAL_MINUTES = UI_HEALTH_CHECK_INTERVAL_DAYS * 24 * 60;
  var UI_HEALTH_CHECK_TIMEOUT_MS = 45e3;
  var UI_HEALTH_CHECK_TAB_READY_TIMEOUT_MS = 3e4;
  var UI_HEALTH_CHECK_MESSAGE_TIMEOUT_MS = 1500;
  var UI_HEALTH_CHECK_MESSAGE_ATTEMPTS = 10;
  var UI_HEALTH_CHECK_MESSAGE = "RUN_SCHEDULED_UI_CHECK";
  var UI_HEALTH_CHECK_STATE_KEY = "vahanUiHealthCheck";
  var PENDING_DEV_NOTIFICATION_KEY = "vahanUiPendingDevNotification";
  var UI_HEALTH_SCHEDULE_PATH = "/api/ui-health/schedule";
  var UI_HEALTH_LOG_PATH = "/api/ui-health/logs";
  var UI_HEALTH_PENDING_LOGS_KEY = "vahanUiHealthPendingLogs";
  var UI_HEALTH_LOG_TIMEOUT_MS = 15e3;
  var UI_HEALTH_OFFICIAL_URL = "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en";
  var UI_HEALTH_OFFICIAL_HOST = "analytics.parivahan.gov.in";
  var UI_HEALTH_REPORT_PATH = "/analytics/vahanpublicreport";
  var UI_HEALTH_OFFICIAL_TAB_MATCHES = Object.freeze([
    "https://analytics.parivahan.gov.in/analytics/vahanpublicreport*"
  ]);
  var DATA_CHANGED_STATUS = "DATA_CHANGED";
  var wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  function withTimeout(promise, timeoutMs, message) {
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => reject(new Error(message)), timeoutMs);
      promise.then(
        (value2) => {
          clearTimeout(timeoutId);
          resolve(value2);
        },
        (error) => {
          clearTimeout(timeoutId);
          reject(error);
        }
      );
    });
  }
  function now() {
    return (/* @__PURE__ */ new Date()).toISOString();
  }
  function createCheckId() {
    if (typeof globalThis.crypto?.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  function errorMessage(error) {
    return String(error?.message || error || "Unknown scheduled health-check error").replace(/\s+/g, " ").trim().slice(0, 300);
  }
  async function assertNoVahanAuthHold(chromeApi, tabId) {
    const stored = await chromeApi.storage.local.get(VAHAN_AUTH_HOLD_KEY);
    const hold = stored?.[VAHAN_AUTH_HOLD_KEY];
    if (isVahanAuthHoldActive(hold, Date.now(), tabId)) {
      throw new Error(`${hold.code}: ${vahanAuthHoldMessage(hold)}`);
    }
  }
  function normalizeIntervalDays(value2, fallback = DEFAULT_UI_HEALTH_CHECK_INTERVAL_DAYS) {
    const numeric = Number(value2);
    if (Number.isInteger(numeric) && numeric >= MIN_UI_HEALTH_CHECK_INTERVAL_DAYS && numeric <= MAX_UI_HEALTH_CHECK_INTERVAL_DAYS) {
      return numeric;
    }
    return fallback;
  }
  function intervalMinutesForDays(intervalDays) {
    return intervalDays * 24 * 60;
  }
  function isReportPath(value2) {
    return String(value2 || "").replace(/\/+$/, "") === UI_HEALTH_REPORT_PATH;
  }
  function isUiHealthOfficialUrl(value2) {
    try {
      const url2 = new URL(String(value2 || ""));
      return url2.protocol === "https:" && url2.hostname === UI_HEALTH_OFFICIAL_HOST && url2.port === "" && isReportPath(url2.pathname);
    } catch {
      return false;
    }
  }
  async function findUiHealthOfficialTab(chromeApi) {
    if (typeof chromeApi.tabs?.query !== "function") return null;
    const tabs = await chromeApi.tabs.query({ url: UI_HEALTH_OFFICIAL_TAB_MATCHES });
    const validTabs = (tabs || []).filter(
      (tab) => tab?.id !== void 0 && isUiHealthOfficialUrl(tab.url)
    );
    return validTabs.find((tab) => tab.active) || validTabs[0] || null;
  }
  async function findUiHealthActiveTab(chromeApi) {
    if (typeof chromeApi.tabs?.query !== "function") return null;
    const tabs = await chromeApi.tabs.query({ active: true, lastFocusedWindow: true });
    return tabs?.[0] || null;
  }
  async function getVerifiedUiHealthTab(chromeApi, tabId) {
    const tab = await chromeApi.tabs.get(tabId);
    if (isUiHealthOfficialUrl(tab?.url)) return tab;
    throw new Error(
      `Health checks can run only on the official VAHAN page ${UI_HEALTH_OFFICIAL_URL}. Current URL: ${tab?.url || "unknown"}.`
    );
  }
  function healthCheckPageUrl(tab, fallback = UI_HEALTH_OFFICIAL_URL) {
    const value2 = String(tab?.url || "").trim();
    return value2 || fallback;
  }
  function missingOfficialTabError() {
    return `No official VAHAN tab is open, or the URL is incorrect. Open ${UI_HEALTH_OFFICIAL_URL} and try again.`;
  }
  function noOfficialTabWithActivePageError(tab) {
    return `No official VAHAN tab is open. The current tab URL is ${tab?.url || "unknown"}. Open ${UI_HEALTH_OFFICIAL_URL} and try again.`;
  }
  async function loadBackendSchedule(chromeApi, fetchImpl) {
    if (typeof fetchImpl !== "function") return null;
    const stored = await chromeApi.storage.local.get("runnerConfig");
    const runnerConfig = stored?.runnerConfig || {};
    const serverUrl = String(runnerConfig.serverUrl || "").trim().replace(/\/+$/, "");
    if (!/^https?:\/\//i.test(serverUrl)) return null;
    const response = await fetchImpl(`${serverUrl}${UI_HEALTH_SCHEDULE_PATH}`, {
      headers: {
        "X-VAHAN-RUNNER-TOKEN": String(runnerConfig.token || ""),
        "X-VAHAN-RUNNER-ID": String(runnerConfig.runnerId || "")
      }
    });
    if (!response?.ok) {
      throw new Error(`Could not load the check schedule from the backend (${response?.status || "unknown"}).`);
    }
    const payload = await response.json();
    const intervalDays = normalizeIntervalDays(payload?.intervalDays, null);
    if (intervalDays === null) {
      throw new Error("The backend returned an invalid check interval.");
    }
    return intervalDays;
  }
  async function postHealthCheck(chromeApi, healthCheck, fetchImpl) {
    if (typeof fetchImpl !== "function") {
      throw new Error("Backend log upload is unavailable in this extension runtime.");
    }
    const stored = await chromeApi.storage.local.get("runnerConfig");
    const runnerConfig = stored?.runnerConfig || {};
    const serverUrl = String(runnerConfig.serverUrl || "").trim().replace(/\/+$/, "");
    if (!/^https?:\/\//i.test(serverUrl)) {
      throw new Error("Configure the backend address before uploading UI health logs.");
    }
    const response = await withTimeout(
      fetchImpl(`${serverUrl}${UI_HEALTH_LOG_PATH}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-VAHAN-RUNNER-TOKEN": String(runnerConfig.token || ""),
          "X-VAHAN-RUNNER-ID": String(runnerConfig.runnerId || "")
        },
        body: JSON.stringify({
          healthCheck,
          pageUrl: healthCheck.pageUrl || UI_HEALTH_OFFICIAL_URL,
          runnerId: runnerConfig.runnerId || null
        })
      }),
      UI_HEALTH_LOG_TIMEOUT_MS,
      "Timed out while sending the UI health log to the backend."
    );
    if (!response?.ok) {
      throw new Error(`Could not upload the UI health log to the backend (${response?.status || "unknown"}).`);
    }
    return response.json();
  }
  function normalizeControl(control = {}) {
    return {
      name: String(control.name || ""),
      selector: String(control.selector || ""),
      tag: String(control.tag || ""),
      id: String(control.id || ""),
      nameAttr: String(control.nameAttr ?? control.name_attr ?? ""),
      multiple: Boolean(control.multiple)
    };
  }
  function normalizeDataSnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== "object") return null;
    const controls = {};
    for (const [name, control] of Object.entries(snapshot.controls || {})) {
      controls[name] = {
        selector: String(control?.selector || ""),
        optionCount: Number.isFinite(Number(control?.optionCount)) ? Number(control.optionCount) : 0,
        digest: String(control?.digest || ""),
        sample: Array.isArray(control?.sample) ? control.sample.slice(0, 8).map((option) => ({
          label: String(option?.label || ""),
          value: String(option?.value || "")
        })) : []
      };
    }
    return {
      version: String(snapshot.version || "v1"),
      signature: String(snapshot.signature || ""),
      controls
    };
  }
  function normalizeContract(contract = {}) {
    return {
      contractVersion: String(contract.contractVersion || ""),
      signature: String(contract.signature || ""),
      path: String(contract.path || contract.urlPath || ""),
      formAction: String(contract.formAction || ""),
      controls: Array.isArray(contract.controls) ? contract.controls.map(normalizeControl) : [],
      dataSnapshot: normalizeDataSnapshot(contract.dataSnapshot)
    };
  }
  function compareDataSnapshots(previous, current) {
    if (!previous?.signature || !current?.signature) return [];
    const previousControls = previous?.controls || {};
    const currentControls = current?.controls || {};
    const names = /* @__PURE__ */ new Set([
      ...Object.keys(previousControls),
      ...Object.keys(currentControls)
    ]);
    return [...names].sort().filter((name) => {
      const before = previousControls[name];
      const after = currentControls[name];
      if (!before || !after) return Boolean(before || after);
      return before.optionCount !== after.optionCount || before.digest !== after.digest;
    }).map((name) => ({
      name,
      selector: currentControls[name]?.selector || previousControls[name]?.selector || "",
      previous: previousControls[name] || null,
      current: currentControls[name] || null
    }));
  }
  function summarizeContract(contract) {
    const normalized = normalizeContract(contract);
    return {
      ...normalized,
      controls: normalized.controls,
      dataSnapshot: normalized.dataSnapshot
    };
  }
  function normalizeUiDriftReport(report = {}) {
    return {
      code: String(report.code || "UI_DRIFT"),
      step: String(report.step || "scheduled-health-check"),
      title: String(report.title || "UI structure does not match the contract"),
      target: String(report.target || "VAHAN Public Report page"),
      expected: String(report.expected || "no data"),
      actual: String(report.actual || "no data"),
      action: String(report.action || "A developer should review the UI contract."),
      message: String(report.message || "A change was detected on the VAHAN Public Report page."),
      diagnostics: report.diagnostics && typeof report.diagnostics === "object" ? report.diagnostics : {}
    };
  }
  function normalizeUiDriftReports(response = {}) {
    const reports = Array.isArray(response.uiDrifts) && response.uiDrifts.length > 0 ? response.uiDrifts : response.uiDrift ? [response.uiDrift] : [];
    return reports.map((report) => normalizeUiDriftReport(report));
  }
  function dataChangedReport(changes, previousContract, currentContract) {
    const target = changes.length === 1 ? changes[0].name : `${changes.length} controls containing option data`;
    const actual = changes.map((change) => {
      const before = change.previous;
      const after = change.current;
      return `${change.name}: ${before?.optionCount ?? 0} option/${before?.digest || "missing"} \u2192 ${after?.optionCount ?? 0} option/${after?.digest || "missing"}`;
    }).join("; ");
    return {
      code: "UI_DRIFT_OPTION_DATA_CHANGED",
      step: "scheduled-health-check",
      title: "Option data on the VAHAN Public Report page has changed",
      target,
      expected: "The option data matches the previous check",
      actual,
      action: "A developer should verify the data change, update the adapter if needed, and rerun the UI checks.",
      message: `A data change was detected at ${target}. The tool logged it for review.`,
      diagnostics: {
        previousDataSignature: previousContract?.dataSnapshot?.signature || "",
        currentDataSignature: currentContract?.dataSnapshot?.signature || "",
        changes
      }
    };
  }
  async function queueDevNotification(chromeApi, healthCheck) {
    if (!["UI_DRIFT", DATA_CHANGED_STATUS].includes(healthCheck.status)) return null;
    const stored = await chromeApi.storage.local.get(PENDING_DEV_NOTIFICATION_KEY);
    const previous = stored[PENDING_DEV_NOTIFICATION_KEY];
    const reports = Array.isArray(healthCheck.reports) && healthCheck.reports.length > 0 ? healthCheck.reports : healthCheck.report ? [healthCheck.report] : [];
    const primaryReport = healthCheck.report || reports[0] || null;
    const sameAlert = previous?.report?.code === primaryReport?.code && previous?.report?.target === primaryReport?.target;
    const notification = {
      schemaVersion: "v1",
      type: healthCheck.status === DATA_CHANGED_STATUS ? "VAHAN_UI_DATA_CHANGED" : "VAHAN_UI_DRIFT",
      alertType: healthCheck.status,
      delivery: "PENDING_CONFIGURATION",
      firstDetectedAt: sameAlert ? previous.firstDetectedAt : healthCheck.checkedAt,
      lastDetectedAt: healthCheck.checkedAt,
      occurrences: sameAlert ? Number(previous.occurrences || 0) + 1 : 1,
      errorCount: Number(healthCheck.errorCount || reports.length || 0),
      report: primaryReport,
      reports
    };
    await chromeApi.storage.local.set({ [PENDING_DEV_NOTIFICATION_KEY]: notification });
    return notification;
  }
  async function flushPendingHealthLogs(chromeApi, fetchImpl) {
    const stored = await chromeApi.storage.local.get(UI_HEALTH_PENDING_LOGS_KEY);
    const pending = Array.isArray(stored[UI_HEALTH_PENDING_LOGS_KEY]) ? stored[UI_HEALTH_PENDING_LOGS_KEY].filter((item) => item && typeof item === "object") : [];
    let lastResult = null;
    let lastError = null;
    while (pending.length > 0) {
      try {
        lastResult = await postHealthCheck(chromeApi, pending[0], fetchImpl);
        pending.shift();
      } catch (error) {
        lastError = errorMessage(error);
        break;
      }
    }
    await chromeApi.storage.local.set({ [UI_HEALTH_PENDING_LOGS_KEY]: pending });
    return {
      ok: pending.length === 0,
      pendingCount: pending.length,
      lastResult,
      error: lastError
    };
  }
  async function deliverHealthLog(chromeApi, healthCheck, fetchImpl) {
    await flushPendingHealthLogs(chromeApi, fetchImpl);
    try {
      const result = await postHealthCheck(chromeApi, healthCheck, fetchImpl);
      const pending = await chromeApi.storage.local.get(UI_HEALTH_PENDING_LOGS_KEY);
      return {
        ...result || {},
        ok: true,
        pendingCount: Array.isArray(pending[UI_HEALTH_PENDING_LOGS_KEY]) ? pending[UI_HEALTH_PENDING_LOGS_KEY].length : 0
      };
    } catch (error) {
      const stored = await chromeApi.storage.local.get(UI_HEALTH_PENDING_LOGS_KEY);
      const pending = Array.isArray(stored[UI_HEALTH_PENDING_LOGS_KEY]) ? stored[UI_HEALTH_PENDING_LOGS_KEY] : [];
      pending.push(healthCheck);
      await chromeApi.storage.local.set({ [UI_HEALTH_PENDING_LOGS_KEY]: pending });
      return {
        ok: false,
        queued: true,
        pendingCount: pending.length,
        error: errorMessage(error)
      };
    }
  }
  async function persistUiHealthCheck(chromeApi, healthCheck, fetchImpl) {
    const identifiedHealthCheck = {
      ...healthCheck,
      checkId: healthCheck.checkId || createCheckId()
    };
    const notification = await queueDevNotification(chromeApi, identifiedHealthCheck);
    await chromeApi.storage.local.set({
      [UI_HEALTH_CHECK_STATE_KEY]: identifiedHealthCheck,
      ...notification ? { [PENDING_DEV_NOTIFICATION_KEY]: notification } : {}
    });
    const saved = {
      ...identifiedHealthCheck,
      backendLog: await deliverHealthLog(chromeApi, identifiedHealthCheck, fetchImpl)
    };
    await chromeApi.storage.local.set({ [UI_HEALTH_CHECK_STATE_KEY]: saved });
    return saved;
  }
  function waitForTabReady(chromeApi, tabId, timeoutMs = UI_HEALTH_CHECK_TAB_READY_TIMEOUT_MS) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const onUpdated = (updatedTabId, changeInfo) => {
        if (updatedTabId === tabId && changeInfo.status === "complete") finish(resolve);
      };
      const finish = (callback, value2) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeoutId);
        chromeApi.tabs.onUpdated?.removeListener(onUpdated);
        callback(value2);
      };
      const timeoutId = setTimeout(
        () => finish(reject, new Error("Timed out while loading the VAHAN Public Report health-check tab.")),
        timeoutMs
      );
      chromeApi.tabs.onUpdated?.addListener(onUpdated);
      chromeApi.tabs.get(tabId).then((tab) => {
        if (tab.status === "complete") finish(resolve);
      }).catch(() => {
      });
    });
  }
  async function requestUiHealthCheck(chromeApi, tabId, retryDelayMs = 500, requireOfficial = true) {
    let lastError;
    let recoveryAttempted = false;
    for (let attempt = 0; attempt < UI_HEALTH_CHECK_MESSAGE_ATTEMPTS; attempt += 1) {
      try {
        await assertNoVahanAuthHold(chromeApi, tabId);
        return await withTimeout(
          chromeApi.tabs.sendMessage(tabId, {
            type: UI_HEALTH_CHECK_MESSAGE,
            requireOfficial
          }),
          UI_HEALTH_CHECK_MESSAGE_TIMEOUT_MS,
          "Timed out while waiting for the VAHAN UI health-check content script."
        );
      } catch (error) {
        lastError = error;
        try {
          await assertNoVahanAuthHold(chromeApi, tabId);
        } catch (authError) {
          throw authError;
        }
        if (!recoveryAttempted && typeof chromeApi.scripting?.executeScript === "function") {
          recoveryAttempted = true;
          try {
            await chromeApi.scripting.executeScript({
              target: { tabId },
              files: ["ui-drift/guard.js", "ui-drift/health-check-content.js"]
            });
          } catch (recoveryError) {
            lastError = recoveryError;
          }
        }
        await wait(retryDelayMs);
      }
    }
    throw lastError || new Error("VAHAN Public Report health-check content script did not respond.");
  }
  function createUiHealthCheckController(chromeApi, options = {}) {
    const fallbackIntervalDays = normalizeIntervalDays(
      options.intervalDays,
      normalizeIntervalDays(
        Number(options.intervalMinutes) / (24 * 60),
        DEFAULT_UI_HEALTH_CHECK_INTERVAL_DAYS
      )
    );
    let intervalDays = fallbackIntervalDays;
    const checkTimeoutMs = options.checkTimeoutMs || UI_HEALTH_CHECK_TIMEOUT_MS;
    const tabReadyTimeoutMs = options.tabReadyTimeoutMs || UI_HEALTH_CHECK_TAB_READY_TIMEOUT_MS;
    const retryDelayMs = options.retryDelayMs ?? 500;
    const fetchImpl = options.fetch || globalThis.fetch;
    let activeHealthCheck = null;
    async function ensureAlarm({ force = false, requestedIntervalDays } = {}) {
      if (!chromeApi.alarms?.get || !chromeApi.alarms?.create) {
        return { ok: false, reason: "Chrome alarms API is unavailable." };
      }
      if (requestedIntervalDays !== void 0) {
        const normalized = normalizeIntervalDays(requestedIntervalDays, null);
        if (normalized === null) {
          return {
            ok: false,
            reason: `The check interval must be between ${MIN_UI_HEALTH_CHECK_INTERVAL_DAYS} and ${MAX_UI_HEALTH_CHECK_INTERVAL_DAYS} days.`,
            intervalDays
          };
        }
        intervalDays = normalized;
      }
      const intervalMinutes = intervalMinutesForDays(intervalDays);
      const existing = await chromeApi.alarms.get(UI_HEALTH_CHECK_ALARM);
      if (!force && existing && Number(existing.periodInMinutes) === intervalMinutes) {
        return { ok: true, created: false, intervalDays, alarm: existing };
      }
      await chromeApi.alarms.create(UI_HEALTH_CHECK_ALARM, {
        delayInMinutes: intervalMinutes,
        periodInMinutes: intervalMinutes
      });
      return {
        ok: true,
        created: !existing,
        updated: Boolean(existing),
        intervalDays
      };
    }
    async function updateSchedule(requestedIntervalDays) {
      return ensureAlarm({ force: true, requestedIntervalDays });
    }
    async function refreshScheduleFromBackend() {
      try {
        const configuredIntervalDays = await loadBackendSchedule(chromeApi, fetchImpl);
        if (configuredIntervalDays === null) {
          return {
            ok: false,
            reason: "Backend schedule is unavailable; keeping the current extension schedule.",
            intervalDays
          };
        }
        return updateSchedule(configuredIntervalDays);
      } catch (error) {
        return { ok: false, reason: errorMessage(error), intervalDays };
      }
    }
    async function execute(trigger, requestedTabId) {
      const startedAt = now();
      const previousState = await chromeApi.storage.local.get(UI_HEALTH_CHECK_STATE_KEY);
      const previousHealthCheck = previousState[UI_HEALTH_CHECK_STATE_KEY];
      const tabId = requestedTabId;
      let pageUrl = UI_HEALTH_OFFICIAL_URL;
      try {
        if (!tabId) throw new Error("Chrome did not return a health-check tab ID.");
        const candidate = await chromeApi.tabs.get(tabId);
        pageUrl = healthCheckPageUrl(candidate);
        const tab = await getVerifiedUiHealthTab(chromeApi, tabId);
        pageUrl = healthCheckPageUrl(tab, pageUrl);
        await assertNoVahanAuthHold(chromeApi, tabId);
        await waitForTabReady(chromeApi, tabId, tabReadyTimeoutMs);
        const readyTab = await getVerifiedUiHealthTab(chromeApi, tabId);
        pageUrl = healthCheckPageUrl(readyTab, pageUrl);
        await assertNoVahanAuthHold(chromeApi, tabId);
        const response = await withTimeout(
          requestUiHealthCheck(chromeApi, tabId, retryDelayMs, true),
          checkTimeoutMs,
          "Timed out while checking the VAHAN UI contract."
        );
        const checkedAt = now();
        if (response?.ok && response.contract) {
          const contract = summarizeContract(response.contract);
          const changes = compareDataSnapshots(
            previousHealthCheck?.contract?.dataSnapshot,
            contract.dataSnapshot
          );
          if (changes.length > 0) {
            const report = dataChangedReport(
              changes,
              previousHealthCheck?.contract,
              contract
            );
            return persistUiHealthCheck(chromeApi, {
              status: DATA_CHANGED_STATUS,
              trigger,
              startedAt,
              checkedAt,
              pageUrl,
              contract,
              report,
              reports: [report],
              errorCount: 1
            }, fetchImpl);
          }
          return persistUiHealthCheck(chromeApi, {
            status: "PASS",
            trigger,
            startedAt,
            checkedAt,
            pageUrl,
            contract,
            reports: [],
            errorCount: 0
          }, fetchImpl);
        }
        const reports = normalizeUiDriftReports(response);
        if (reports.length > 0) {
          return persistUiHealthCheck(chromeApi, {
            status: "UI_DRIFT",
            trigger,
            startedAt,
            checkedAt,
            pageUrl,
            report: reports[0],
            reports,
            errorCount: Number(response.errorCount) || reports.length
          }, fetchImpl);
        }
        return persistUiHealthCheck(chromeApi, {
          status: "CHECK_ERROR",
          trigger,
          startedAt,
          checkedAt,
          pageUrl,
          error: errorMessage(response?.error || "The VAHAN Public Report health check returned no result.")
        }, fetchImpl);
      } catch (error) {
        return persistUiHealthCheck(chromeApi, {
          status: "CHECK_ERROR",
          trigger,
          startedAt,
          checkedAt: now(),
          pageUrl,
          error: errorMessage(error)
        }, fetchImpl);
      }
    }
    async function runOnOfficialTab(trigger = "alarm") {
      let tab;
      try {
        tab = await findUiHealthOfficialTab(chromeApi);
      } catch (error) {
        return persistUiHealthCheck(chromeApi, {
          status: "CHECK_ERROR",
          trigger,
          startedAt: now(),
          checkedAt: now(),
          pageUrl: UI_HEALTH_OFFICIAL_URL,
          error: errorMessage(error)
        }, fetchImpl);
      }
      if (!tab?.id) {
        let activeTab = null;
        try {
          activeTab = await findUiHealthActiveTab(chromeApi);
        } catch {
        }
        return persistUiHealthCheck(chromeApi, {
          status: "CHECK_ERROR",
          trigger,
          startedAt: now(),
          checkedAt: now(),
          pageUrl: healthCheckPageUrl(activeTab),
          error: activeTab ? noOfficialTabWithActivePageError(activeTab) : missingOfficialTabError()
        }, fetchImpl);
      }
      return execute(trigger, tab.id);
    }
    async function getState() {
      return chromeApi.storage.local.get([
        UI_HEALTH_CHECK_STATE_KEY,
        PENDING_DEV_NOTIFICATION_KEY,
        UI_HEALTH_PENDING_LOGS_KEY
      ]);
    }
    function run(trigger = "alarm") {
      if (!activeHealthCheck) {
        activeHealthCheck = runOnOfficialTab(trigger).finally(() => {
          activeHealthCheck = null;
        });
      }
      return activeHealthCheck;
    }
    return Object.freeze({
      ensureAlarm,
      getState,
      refreshScheduleFromBackend,
      run,
      updateSchedule
    });
  }
  function registerUiHealthCheck(chromeApi, options = {}) {
    const controller = createUiHealthCheckController(chromeApi, options);
    const ensure = () => {
      controller.ensureAlarm().catch((error) => {
        console.error("[VAHAN UI HEALTH] Could not create the check schedule:", errorMessage(error));
      });
    };
    chromeApi.runtime?.onInstalled?.addListener(ensure);
    chromeApi.runtime?.onStartup?.addListener(ensure);
    chromeApi.alarms?.onAlarm?.addListener((alarm) => {
      if (alarm.name === UI_HEALTH_CHECK_ALARM) void controller.run("alarm");
    });
    chromeApi.runtime?.onMessage?.addListener((message, _sender, sendResponse) => {
      if (message?.type === "GET_UI_HEALTH_CHECK") {
        controller.getState().then(sendResponse).catch((error) => sendResponse({ error: errorMessage(error) }));
        return true;
      }
      if (message?.type === "RUN_UI_HEALTH_CHECK_NOW") {
        controller.run("manual").then((healthCheck) => sendResponse({
          ok: healthCheck.status === "PASS",
          healthCheck
        })).catch((error) => sendResponse({ ok: false, error: errorMessage(error) }));
        return true;
      }
      return void 0;
    });
    ensure();
    return controller;
  }

  // src/background.js
  var DEFAULT_RUNNER_CONFIG = Object.freeze({
    serverUrl: "http://127.0.0.1:8000",
    runnerName: "VAHAN Chrome",
    token: "change-me"
  });
  var HEARTBEAT_INTERVAL_MS = 2e4;
  var RUNNER_CONNECTION_ALARM = "runner-connection-watchdog";
  var VAHAN_URL = "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en";
  var VAHAN_PAGE_STALL_TIMEOUT_MS = 1e4;
  var VAHAN_PAGE_STALL_CHECK_INTERVAL_MS = 1e3;
  var VAHAN_PAGE_LIVENESS_PROBE_INTERVAL_MS = 2e3;
  var VAHAN_PAGE_STALL_MONITORED_STAGES = /* @__PURE__ */ new Set([
    "OPENING_VAHAN",
    "FILLING_FILTERS",
    "CAPTURING_CAPTCHA",
    "SUBMITTING",
    "WAITING_CAPTCHA",
    "WAITING_RESULT",
    "DOWNLOADING_REPORT",
    "UPLOADING_REPORT"
  ]);
  var INITIAL_PAGE_LOAD_TIMEOUT_MS = 75e3;
  var MAX_TAB_IDLE_AGE_MS = 10 * 60 * 1e3;
  var VAHAN_OPTION_SELECTORS = Object.freeze({
    archivedFlags: { selector: "#archivedFlags", multiple: true },
    period: { selector: "#reportType" },
    financialYears: { selector: "#financialYearSelect", multiple: true },
    reportYear: { selector: "#reportYear" },
    reportMonth: { selector: "#reportMonth" },
    states: { selector: "#stateName", multiple: true },
    rtos: { selector: "#rtoCode", multiple: true },
    emissions: { selector: "#vehicleEmission", multiple: true },
    categoryGroups: { selector: "#vehicleCategoryGroup", multiple: true },
    subCategories: { selector: "#vehicleSubCategory", multiple: true },
    classes: { selector: "#vehicleClass", multiple: true },
    fuels: { selector: "#vehicleFuel", multiple: true },
    evTypes: { selector: "#evType", multiple: true },
    statuses: { selector: "#vehicleStatus", multiple: true },
    ownerTypes: { selector: "#vehicleOwnerType", multiple: true },
    vehicleType: { selector: "#vehicleType" },
    fitness: { selector: "#fitnessCheck" },
    delhiNcr: { selector: "#delhiNcr" },
    yAxis: { selector: "#yAxis" },
    xAxis: { selector: "#xAxis" }
  });
  var socket;
  var heartbeatTimer;
  var reconnectTimer;
  var runnerConnectionTask;
  var runnerReconnectRequested = false;
  var activeConfig;
  var activeJobId;
  var cancelledJobIds = /* @__PURE__ */ new Set();
  var pendingBlobResolver;
  var pendingReportCapture;
  var reportJobInFlight;
  var vahanPageStallCheckTimer;
  var vahanPageStallCheckTask;
  var vahanPageHeartbeats = /* @__PURE__ */ new Map();
  var vahanPageStallRecoveryJobs = /* @__PURE__ */ new Set();
  var pendingReportUploadController;
  var uiHealthCheckController;
  var vahanAuthHold;
  var authHoldWrite = Promise.resolve();
  var authChallengeWaiters = /* @__PURE__ */ new Set();
  var authFailureReportedJobs = /* @__PURE__ */ new Set();
  var tabActivityTimestamps = /* @__PURE__ */ new Map();
  var tabLastErrors = /* @__PURE__ */ new Map();
  var vahanPageLivenessProbes = /* @__PURE__ */ new Map();
  var successfulApplyCountQueue = Promise.resolve();
  function serializeSuccessfulApplyCountUpdate(operation) {
    const update = successfulApplyCountQueue.catch(() => {
    }).then(operation);
    successfulApplyCountQueue = update.catch(() => {
    });
    return update;
  }
  function normalizeSuccessfulApplyCount(value2) {
    const count = Number(value2);
    return Number.isSafeInteger(count) && count > 0 ? count : 0;
  }
  function recordSuccessfulApplyClick(clickId) {
    return serializeSuccessfulApplyCountUpdate(async () => {
      const stored = await chrome.storage.local.get([
        "successfulApplyCount",
        "successfulApplyClickIds"
      ]);
      const clickIds = Array.isArray(stored.successfulApplyClickIds) ? stored.successfulApplyClickIds.filter((id) => typeof id === "string") : [];
      const count = normalizeSuccessfulApplyCount(stored.successfulApplyCount);
      if (clickIds.includes(clickId)) return { count, duplicate: true };
      const nextCount = count + 1;
      clickIds.push(clickId);
      await chrome.storage.local.set({
        successfulApplyCount: nextCount,
        successfulApplyClickIds: clickIds.slice(-1024)
      });
      return { count: nextCount, duplicate: false };
    });
  }
  async function flushPendingSuccessfulApplyClicks() {
    if (!socket?.connected) return;
    const stored = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
    const pending = Array.isArray(stored.pendingSuccessfulApplyClicks) ? stored.pendingSuccessfulApplyClicks.filter((entry) => entry && typeof entry.jobId === "string" && typeof entry.clickId === "string") : [];
    for (const entry of pending) {
      if (!socket?.connected) return;
      let response;
      try {
        response = await socket.timeout(5e3).emitWithAck("job:apply-clicked", entry);
      } catch {
        return;
      }
      if (response?.ok !== true) {
        const latest2 = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
        const current2 = Array.isArray(latest2.pendingSuccessfulApplyClicks) ? latest2.pendingSuccessfulApplyClicks : [];
        await chrome.storage.local.set({
          pendingSuccessfulApplyClicks: current2.filter((item) => item?.jobId !== entry.jobId || item?.clickId !== entry.clickId)
        });
        continue;
      }
      const latest = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
      const current = Array.isArray(latest.pendingSuccessfulApplyClicks) ? latest.pendingSuccessfulApplyClicks : [];
      await chrome.storage.local.set({
        pendingSuccessfulApplyClicks: current.filter((item) => item?.jobId !== entry.jobId || item?.clickId !== entry.clickId)
      });
    }
  }
  async function queueSuccessfulApplyClickForJob(jobId, clickId) {
    const stored = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
    const pending = Array.isArray(stored.pendingSuccessfulApplyClicks) ? stored.pendingSuccessfulApplyClicks.filter((entry) => entry && typeof entry.jobId === "string" && typeof entry.clickId === "string") : [];
    if (!pending.some((entry) => entry.jobId === jobId && entry.clickId === clickId)) {
      pending.push({ jobId, clickId });
      await chrome.storage.local.set({ pendingSuccessfulApplyClicks: pending.slice(-500) });
    }
    await flushPendingSuccessfulApplyClicks();
    const latest = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
    return !Array.isArray(latest.pendingSuccessfulApplyClicks) || !latest.pendingSuccessfulApplyClicks.some((entry) => entry?.jobId === jobId && entry?.clickId === clickId);
  }
  function resetSuccessfulApplyCount() {
    return serializeSuccessfulApplyCountUpdate(async () => {
      await chrome.storage.local.set({ successfulApplyCount: 0 });
      return { count: 0 };
    });
  }
  var delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  function recordTabActivity(tabId) {
    if (tabId !== void 0 && tabId !== null) {
      tabActivityTimestamps.set(tabId, Date.now());
    }
  }
  var VahanAuthRequiredError = class extends Error {
    constructor(hold) {
      super(vahanAuthHoldMessage(hold));
      this.name = "VahanAuthRequiredError";
      this.code = VAHAN_AUTH_REQUIRED_CODE;
      this.hold = hold;
    }
  };
  var VahanSessionExpiredError = class extends Error {
    constructor(message = vahanSessionExpiredMessage()) {
      super(message);
      this.name = "VahanSessionExpiredError";
      this.code = VAHAN_SESSION_EXPIRED_CODE;
    }
  };
  var VahanUnreachableError = class extends Error {
    constructor(detail = "") {
      super(vahanUnreachableMessage(detail));
      this.name = "VahanUnreachableError";
      this.code = VAHAN_UNREACHABLE_CODE;
      this.detail = detail;
    }
  };
  var VahanServerError = class extends Error {
    constructor(statusCode = 500) {
      super(`VAHAN server error (HTTP ${statusCode}). The site may be under maintenance.`);
      this.name = "VahanServerError";
      this.code = VAHAN_SERVER_ERROR_CODE;
      this.statusCode = statusCode;
    }
  };
  async function loadVahanAuthHold() {
    const stored = await chrome.storage.local.get(VAHAN_AUTH_HOLD_KEY);
    vahanAuthHold = stored?.[VAHAN_AUTH_HOLD_KEY] || void 0;
    if (!isVahanAuthHoldActive(vahanAuthHold)) {
      if (vahanAuthHold?.code === VAHAN_AUTH_REQUIRED_CODE && vahanAuthHold.guardVersion !== VAHAN_AUTH_GUARD_VERSION) {
        await chrome.storage.local.remove(VAHAN_AUTH_HOLD_KEY);
      }
      vahanAuthHold = void 0;
      chrome.action.setBadgeText?.({ text: "" });
    }
    return vahanAuthHold;
  }
  function notifyAuthChallengeWaiters(hold) {
    for (const waiter of authChallengeWaiters) {
      if (waiter.tabId === void 0 || hold.tabId === null || waiter.tabId === hold.tabId) {
        waiter.reject(new VahanAuthRequiredError(hold));
      }
    }
  }
  function showAuthHoldBadge(hold) {
    chrome.action.setBadgeText?.({ text: "!" });
    chrome.action.setBadgeBackgroundColor?.({ color: "#b42318" });
    chrome.action.setTitle?.({ title: "VAHAN authentication required \u2014 automation paused" });
    chrome.runtime.sendMessage({ type: "VAHAN_AUTH_REQUIRED", authHold: hold }).catch(() => {
    });
  }
  function recordVahanAuthChallenge(details) {
    const hold = createVahanAuthHold(details, vahanAuthHold);
    vahanAuthHold = hold;
    notifyAuthChallengeWaiters(hold);
    showAuthHoldBadge(hold);
    authHoldWrite = authHoldWrite.catch(() => {
    }).then(async () => {
      await chrome.storage.local.set({ [VAHAN_AUTH_HOLD_KEY]: hold });
      return hold;
    });
    return hold;
  }
  async function clearVahanAuthHold() {
    vahanAuthHold = void 0;
    await chrome.storage.local.remove(VAHAN_AUTH_HOLD_KEY);
    chrome.action.setBadgeText?.({ text: "" });
    chrome.action.setTitle?.({ title: "VAHAN RPA Assistant" });
    chrome.runtime.sendMessage({ type: "VAHAN_AUTH_CLEARED" }).catch(() => {
    });
  }
  async function assertNoVahanAuthHold2(tabId) {
    const hold = vahanAuthHold || await loadVahanAuthHold();
    if (isVahanAuthHoldActive(hold, Date.now(), tabId)) {
      throw new VahanAuthRequiredError(hold);
    }
  }
  function installVahanAuthGuard() {
    if (!chrome.webRequest?.onAuthRequired?.addListener) return;
    chrome.webRequest.onAuthRequired.addListener(
      (details, respond) => {
        if (details.isProxy) {
          respond({});
          return;
        }
        if (!isVahanMainFrameAuthChallenge(details)) {
          respond({ cancel: true });
          return;
        }
        const hold = recordVahanAuthChallenge(details);
        respond({ cancel: true });
      },
      { urls: ["https://analytics.parivahan.gov.in/*"] },
      ["asyncBlocking"]
    );
    chrome.webRequest.onCompleted?.addListener(
      (details) => {
        if (details.type !== "main_frame") return;
        if (details.statusCode >= 500 && isVahanRequestUrl(details.url)) {
          tabLastErrors.set(details.tabId, {
            type: "SERVER_ERROR",
            statusCode: details.statusCode,
            url: details.url,
            timestamp: Date.now()
          });
        }
        if (details.statusCode >= 200 && details.statusCode < 300) {
          if (isVahanPublicReportUrl(details.url)) {
            recordTabActivity(details.tabId);
            tabLastErrors.delete(details.tabId);
          }
          if (!isVahanRequestUrl(details.url) || !vahanAuthHold) return;
          if (vahanAuthHold.tabId !== null && vahanAuthHold.tabId !== details.tabId) return;
          try {
            const completed = new URL(details.url);
            const challenged = new URL(vahanAuthHold.url);
            if (`${completed.origin}${completed.pathname}` !== `${challenged.origin}${challenged.pathname}`) return;
          } catch {
            return;
          }
          clearVahanAuthHold().catch(() => {
          });
        }
      },
      { urls: ["https://analytics.parivahan.gov.in/*"] }
    );
    if (chrome.webNavigation?.onErrorOccurred) {
      chrome.webNavigation.onErrorOccurred.addListener((details) => {
        if (details.frameId === 0 && isVahanRequestUrl(details.url)) {
          tabLastErrors.set(details.tabId, {
            type: "NETWORK_ERROR",
            error: details.error,
            url: details.url,
            timestamp: Date.now()
          });
        }
      });
    }
    chrome.tabs.onRemoved?.addListener((tabId) => {
      tabActivityTimestamps.delete(tabId);
      tabLastErrors.delete(tabId);
      vahanPageHeartbeats.delete(tabId);
      vahanPageLivenessProbes.delete(tabId);
    });
  }
  async function reportJobStatus(jobId, status, error) {
    if (!socket?.connected) throw new Error("Backend is disconnected.");
    const response = await socket.timeout(5e3).emitWithAck("job:status", {
      jobId,
      status,
      ...error ? { error } : {}
    });
    if (!response?.ok) throw new Error(response?.error || `Could not report ${status}.`);
  }
  async function restorePreviousJobTab(activeServerJob) {
    const previousTabId = activeServerJob?.previousTabId;
    const vahanTabId = activeServerJob?.tabId;
    if (!Number.isInteger(previousTabId) || !Number.isInteger(vahanTabId) || previousTabId === vahanTabId) return;
    try {
      const [activeTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      if (activeTab?.id !== vahanTabId) return;
      const previousTab = await chrome.tabs.get(previousTabId);
      if (previousTab.windowId !== activeTab.windowId) return;
      await chrome.tabs.update(previousTabId, { active: true });
    } catch {
    }
  }
  async function finishServerJob(activeServerJob) {
    if (!activeServerJob?.jobId) return;
    const { activeServerJob: storedJob } = await chrome.storage.local.get("activeServerJob");
    if (storedJob?.jobId && storedJob.jobId !== activeServerJob.jobId) return;
    await restorePreviousJobTab(activeServerJob);
    if (activeJobId === activeServerJob.jobId) activeJobId = void 0;
    await chrome.storage.local.remove(["pendingServerJob", "activeServerJob"]);
  }
  async function recoverStalledVahanPage(activeServerJob, stalledForMs) {
    const jobId = activeServerJob?.jobId;
    const tabId = activeServerJob?.tabId;
    if (!jobId || !Number.isInteger(tabId) || vahanPageStallRecoveryJobs.has(jobId)) return;
    vahanPageStallRecoveryJobs.add(jobId);
    let recoveryStarted = false;
    try {
      const { activeServerJob: currentJob } = await chrome.storage.local.get("activeServerJob");
      if (currentJob?.jobId !== jobId || !VAHAN_PAGE_STALL_MONITORED_STAGES.has(currentJob.stage) || activeJobId && activeJobId !== jobId) return;
      const tab = await chrome.tabs.get(tabId);
      const heartbeat = vahanPageHeartbeats.get(tabId);
      if (!isVahanPublicReportUrl(tab.url) || tab.status !== "complete" || tab.discarded || tab.frozen || !heartbeat || Date.now() - heartbeat.receivedAt < VAHAN_PAGE_STALL_TIMEOUT_MS || isVahanAuthHoldActive(vahanAuthHold, Date.now(), tabId)) return;
      const { activeServerJob: latestJob } = await chrome.storage.local.get("activeServerJob");
      if (latestJob?.jobId !== jobId || !VAHAN_PAGE_STALL_MONITORED_STAGES.has(latestJob.stage)) return;
      recoveryStarted = true;
      const seconds = Math.max(10, Math.round(stalledForMs / 1e3));
      const recoveringJob = { ...latestJob, stage: "PAGE_STALLED_RELOADING" };
      cancelledJobIds.add(jobId);
      await chrome.storage.local.set({ activeServerJob: recoveringJob });
      let reloadDetail = "The page was reloaded.";
      try {
        await chrome.tabs.reload(tabId);
      } catch (error) {
        reloadDetail = `Reload failed: ${error.message}`;
      }
      const errorMessage2 = `VAHAN page stopped responding for about ${seconds} seconds. ${reloadDetail} This job was marked failed to prevent stale results.`;
      await reportJobStatus(jobId, "FAILED", errorMessage2).catch((error) => {
        console.warn("[VAHAN EXT] Could not report the stalled page job:", error.message);
      });
      await finishServerJob(recoveringJob);
    } catch (error) {
      console.warn("[VAHAN EXT] Could not recover the stalled VAHAN page:", error.message);
    } finally {
      if (!recoveryStarted) vahanPageStallRecoveryJobs.delete(jobId);
      else {
        vahanPageHeartbeats.delete(tabId);
        vahanPageLivenessProbes.delete(tabId);
      }
    }
  }
  function requestVahanPageLivenessProbe(tabId) {
    if (vahanPageLivenessProbes.has(tabId)) return;
    const probe = chrome.scripting.executeScript({
      target: { tabId },
      func: () => ({ url: location.href, readyState: document.readyState })
    });
    let trackedProbe;
    trackedProbe = probe.then((results) => {
      const result = results?.[0]?.result;
      if (result?.readyState === "complete" && isVahanPublicReportUrl(result.url)) {
        vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: false });
      }
    }).catch((error) => {
      console.debug("[VAHAN EXT] Background page liveness probe did not respond:", error.message);
    }).finally(() => {
      if (vahanPageLivenessProbes.get(tabId) === trackedProbe) {
        vahanPageLivenessProbes.delete(tabId);
      }
    });
    vahanPageLivenessProbes.set(tabId, trackedProbe);
  }
  async function checkVahanPageStall() {
    const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
    if (!activeServerJob?.jobId || !VAHAN_PAGE_STALL_MONITORED_STAGES.has(activeServerJob.stage) || !Number.isInteger(activeServerJob.tabId)) return;
    const tabId = activeServerJob.tabId;
    let tab;
    try {
      tab = await chrome.tabs.get(tabId);
    } catch {
      return;
    }
    if (!isVahanPublicReportUrl(tab.url) || tab.status !== "complete" || tab.discarded || tab.frozen) return;
    let heartbeat = vahanPageHeartbeats.get(tabId);
    if (!heartbeat) {
      heartbeat = { receivedAt: Date.now(), visible: Boolean(tab.active) };
      vahanPageHeartbeats.set(tabId, heartbeat);
      return;
    }
    if (!tab.active && Date.now() - heartbeat.receivedAt >= VAHAN_PAGE_LIVENESS_PROBE_INTERVAL_MS) {
      requestVahanPageLivenessProbe(tabId);
    }
    const stalledForMs = Date.now() - heartbeat.receivedAt;
    if (stalledForMs < VAHAN_PAGE_STALL_TIMEOUT_MS) return;
    await recoverStalledVahanPage(activeServerJob, stalledForMs);
  }
  function startVahanPageStallWatchdog() {
    if (vahanPageStallCheckTimer) return;
    vahanPageStallCheckTimer = setInterval(() => {
      if (vahanPageStallCheckTask) return;
      vahanPageStallCheckTask = checkVahanPageStall().catch((error) => console.warn("[VAHAN EXT] Page responsiveness check failed:", error.message)).finally(() => {
        vahanPageStallCheckTask = void 0;
      });
    }, VAHAN_PAGE_STALL_CHECK_INTERVAL_MS);
  }
  async function publishCaptcha(jobId, captcha) {
    if (!socket?.connected) throw new Error("Backend is disconnected.");
    const response = await socket.timeout(5e3).emitWithAck("captcha:required", {
      jobId,
      captchaId: captcha.captchaId,
      imageDataUrl: captcha.imageDataUrl
    });
    if (!response?.ok) throw new Error(response?.error || "Could not publish CAPTCHA.");
  }
  async function publishCaptchaChange(activeServerJob, captcha, event) {
    if (!captcha?.captchaId || !captcha?.imageDataUrl) {
      throw new Error("VAHAN did not return a valid fresh CAPTCHA.");
    }
    if (captcha.captchaId === activeServerJob.captchaId) {
      throw new Error("VAHAN returned the previous CAPTCHA image. Please try again.");
    }
    const updatedJob = {
      ...activeServerJob,
      captchaId: captcha.captchaId,
      stage: "WAITING_CAPTCHA"
    };
    await chrome.storage.local.set({ activeServerJob: updatedJob });
    await emitWithRetry(event, {
      jobId: activeServerJob.jobId,
      captchaId: captcha.captchaId,
      imageDataUrl: captcha.imageDataUrl
    });
    return captcha;
  }
  async function requestFreshCaptcha(activeServerJob) {
    const captcha = await sendToVahan(activeServerJob.tabId, {
      type: "REFRESH_CAPTCHA",
      previousCaptchaId: activeServerJob.captchaId
    });
    if (!captcha?.ok) throw new Error(captcha?.error || "Could not refresh the official VAHAN CAPTCHA.");
    return captcha;
  }
  async function emitWithRetry(event, payload, attempts = 3) {
    let lastError;
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        if (!socket?.connected) throw new Error("Backend is disconnected.");
        const response = await socket.timeout(5e3).emitWithAck(event, payload);
        if (!response?.ok) throw new Error(response?.error || `${event} was rejected.`);
        return response;
      } catch (error) {
        lastError = error;
        if (attempt < attempts) await delay(500 * attempt);
      }
    }
    throw lastError;
  }
  function assertJobActive(jobId) {
    if (cancelledJobIds.has(jobId)) throw new Error("Job was cancelled.");
  }
  async function verifyTabUrl(tabId) {
    const tab = await chrome.tabs.get(tabId);
    const url2 = tab?.url || "";
    if (isChromeErrorUrl(url2)) {
      const lastError2 = tabLastErrors.get(tabId);
      throw new VahanUnreachableError(lastError2?.error || "Connection error");
    }
    const lastError = tabLastErrors.get(tabId);
    if (lastError && lastError.type === "SERVER_ERROR" && Date.now() - lastError.timestamp < 15e3) {
      throw new VahanServerError(lastError.statusCode);
    }
    if (isVahanRedirectedHomeUrl(url2)) {
      throw new VahanSessionExpiredError();
    }
    return tab;
  }
  async function waitForTabComplete(tabId, timeout = 3e4) {
    await assertNoVahanAuthHold2(tabId);
    const current = await chrome.tabs.get(tabId);
    if (current.status === "complete") {
      await verifyTabUrl(tabId);
      return;
    }
    await new Promise((resolve, reject) => {
      let settled = false;
      const authWaiter = {
        tabId,
        reject: (error) => finish(reject, error)
      };
      const authPoll = setInterval(() => {
        assertNoVahanAuthHold2(tabId).catch((error) => finish(reject, error));
      }, 250);
      const timer = setTimeout(() => {
        finish(reject, new Error("VAHAN page did not finish loading in time."));
      }, timeout);
      const finish = (callback, value2) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        clearInterval(authPoll);
        chrome.tabs.onUpdated.removeListener(listener);
        authChallengeWaiters.delete(authWaiter);
        callback(value2);
      };
      const listener = (updatedId, changeInfo) => {
        if (updatedId !== tabId || changeInfo.status !== "complete") return;
        verifyTabUrl(tabId).then(() => finish(resolve)).catch((error) => finish(reject, error));
      };
      authChallengeWaiters.add(authWaiter);
      chrome.tabs.onUpdated.addListener(listener);
    });
  }
  async function getVahanTab() {
    await assertNoVahanAuthHold2();
    const tabs = await chrome.tabs.query({ url: "https://analytics.parivahan.gov.in/analytics/vahanpublicreport*" });
    let tab = tabs.find((candidate) => !candidate.discarded && !candidate.active) || tabs.find((candidate) => !candidate.discarded) || tabs[0];
    let forceReload = Boolean(tab?.discarded);
    if (tab?.id) {
      const lastActive = tabActivityTimestamps.get(tab.id) || 0;
      const isStale = Date.now() - lastActive > MAX_TAB_IDLE_AGE_MS;
      if (isStale || !isVahanPublicReportUrl(tab.url)) {
        forceReload = true;
      }
    } else {
      tab = await chrome.tabs.create({ url: VAHAN_URL, active: false });
    }
    if (!tab.id) throw new Error("Chrome did not return a VAHAN tab id.");
    if (tab.autoDiscardable !== false) {
      await chrome.tabs.update(tab.id, { autoDiscardable: false });
    }
    if (forceReload) {
      await chrome.tabs.update(tab.id, { url: VAHAN_URL });
    }
    try {
      await waitForTabComplete(tab.id, INITIAL_PAGE_LOAD_TIMEOUT_MS);
    } catch (error) {
      if (error instanceof VahanAuthRequiredError || error instanceof VahanUnreachableError || error instanceof VahanServerError || error instanceof VahanSessionExpiredError) {
        throw error;
      }
      if (!String(error?.message).includes("did not finish loading")) {
        throw error;
      }
      await chrome.tabs.reload(tab.id);
      try {
        await waitForTabComplete(tab.id, INITIAL_PAGE_LOAD_TIMEOUT_MS);
      } catch (retryError) {
        if (retryError instanceof VahanUnreachableError || retryError instanceof VahanServerError || retryError instanceof VahanSessionExpiredError) {
          throw retryError;
        }
        throw new Error("VAHAN page did not finish loading after a retry \u2014 the site may be down or extremely slow.");
      }
    }
    await assertNoVahanAuthHold2(tab.id);
    recordTabActivity(tab.id);
    return tab.id;
  }
  async function getOptionsTab() {
    return getVahanTab();
  }
  async function sendToVahan(tabId, message) {
    let reloadAttempted = false;
    for (let attempt = 0; attempt < 6; attempt += 1) {
      try {
        await assertNoVahanAuthHold2(tabId);
        return await chrome.tabs.sendMessage(tabId, message);
      } catch (error) {
        await assertNoVahanAuthHold2(tabId);
        if (String(error?.message).includes("Receiving end")) {
          try {
            const currentTab = await chrome.tabs.get(tabId);
            if (isChromeErrorUrl(currentTab?.url)) {
              const lastError = tabLastErrors.get(tabId);
              throw new VahanUnreachableError(lastError?.error || "Connection error");
            }
            if (isVahanRedirectedHomeUrl(currentTab?.url)) {
              throw new VahanSessionExpiredError();
            }
          } catch (inspectError) {
            if (inspectError instanceof VahanUnreachableError || inspectError instanceof VahanSessionExpiredError) {
              throw inspectError;
            }
          }
        }
        if (attempt === 0 && String(error?.message).includes("Receiving end")) {
          reloadAttempted = true;
          await chrome.tabs.reload(tabId);
          await waitForTabComplete(tabId);
        }
        if (attempt === 5 || reloadAttempted && attempt > 0) {
          try {
            const finalTab = await chrome.tabs.get(tabId);
            if (isChromeErrorUrl(finalTab?.url)) {
              throw new VahanUnreachableError();
            }
            if (isVahanRedirectedHomeUrl(finalTab?.url)) {
              throw new VahanSessionExpiredError();
            }
          } catch (finalInspectError) {
            if (finalInspectError instanceof VahanUnreachableError || finalInspectError instanceof VahanSessionExpiredError) {
              throw finalInspectError;
            }
          }
          throw error;
        }
        await delay(500);
      }
    }
  }
  function isLikelyExcelDownload(item, tabId) {
    if (!item || item.id === void 0) return false;
    if (Number.isInteger(item.tabId) && item.tabId >= 0 && item.tabId !== tabId) return false;
    const url2 = String(item.url || "").toLocaleLowerCase();
    if (!url2.startsWith("blob:https://analytics.parivahan.gov.in/") && !isVahanRequestUrl(url2)) return false;
    if (url2.startsWith("blob:")) return true;
    const source = `${url2} ${item.filename || ""}`;
    return /(?:\.xlsx?(?:$|[?#])|\.xlsm(?:$|[?#])|excel|spreadsheet|export)/i.test(source);
  }
  async function triggerAndWaitForExcelDownload(activeServerJob) {
    const { tabId, jobId } = activeServerJob;
    const captureId = crypto.randomUUID();
    let resolveBlob;
    let rejectBlob;
    let blobTimer;
    const blobPromise = new Promise((resolve, reject) => {
      resolveBlob = resolve;
      rejectBlob = reject;
      blobTimer = setTimeout(() => {
        reject(new Error("Excel file bytes were not captured within 60 seconds."));
      }, 6e4);
    });
    const onCreated = (item) => {
      if (!isLikelyExcelDownload(item, tabId)) return;
      try {
        chrome.downloads.cancel(item.id, () => {
          chrome.downloads.erase({ id: item.id }, () => {
          });
        });
      } catch (e) {
      }
      if (item.url) {
        sendToVahan(tabId, {
          type: "CAPTURE_EXCEL_DOWNLOAD",
          href: item.url,
          fileName: item.filename?.split(/[\\/]/).pop() || "report.xlsx",
          captureId
        }).catch(() => {
        });
      }
    };
    const blobResolver = (data) => {
      clearTimeout(blobTimer);
      if (data?.error || !data?.dataUrl || !String(data.dataUrl).startsWith("data:")) {
        rejectBlob(new Error(data?.error || "Excel file bytes were not captured correctly."));
      } else {
        resolveBlob(data);
      }
      if (pendingBlobResolver === blobResolver) pendingBlobResolver = void 0;
      resolveBlob = () => {
      };
      rejectBlob = () => {
      };
    };
    pendingBlobResolver = blobResolver;
    pendingReportCapture = { tabId, captureId };
    chrome.downloads.onCreated.addListener(onCreated);
    try {
      const response = await sendToVahan(tabId, { type: "CLICK_EXCEL_DOWNLOAD", captureId });
      if (!response?.ok) {
        rejectBlob(new Error(response?.error || "Could not click the Excel download button."));
      }
      const { dataUrl, fileName } = await blobPromise;
      const { activeServerJob: currentJob } = await chrome.storage.local.get("activeServerJob");
      if (currentJob?.jobId !== jobId) throw new Error("The active job changed before the Excel upload.");
      assertJobActive(jobId);
      await chrome.storage.local.set({
        activeServerJob: { ...activeServerJob, stage: "UPLOADING_REPORT" }
      });
      const config = await loadRunnerConfig();
      const serverUrl = config.serverUrl || "http://127.0.0.1:8000";
      const blobResponse = await fetch(dataUrl);
      if (!blobResponse.ok) {
        throw new Error(`Could not decode the captured Excel file (${blobResponse.status}).`);
      }
      const blob = await blobResponse.blob();
      if (!blob.size) throw new Error("The captured Excel file is empty.");
      const uploadFileName = activeServerJob?.scenarioName ? `${activeServerJob.scenarioName.replace(/[\\/*?:"<>|\r\n\t]/g, "_").trim()}.xlsx` : fileName || "report.xlsx";
      const uploadController = new AbortController();
      pendingReportUploadController = uploadController;
      try {
        assertJobActive(jobId);
        const result = await uploadCapturedReport({
          serverUrl,
          jobId,
          runnerId: config.runnerId,
          token: config.token,
          blob,
          fileName: uploadFileName,
          signal: uploadController.signal
        });
        assertJobActive(jobId);
        return result;
      } finally {
        if (pendingReportUploadController === uploadController) pendingReportUploadController = void 0;
      }
    } finally {
      clearTimeout(blobTimer);
      chrome.downloads.onCreated.removeListener(onCreated);
      if (pendingBlobResolver === blobResolver) pendingBlobResolver = void 0;
      if (pendingReportCapture?.captureId === captureId) pendingReportCapture = void 0;
      await chrome.tabs.sendMessage(tabId, { type: "END_EXCEL_CAPTURE", captureId }).catch(() => {
      });
    }
  }
  async function executeJob(job) {
    const jobId = String(job?.jobId || "");
    if (!jobId) return;
    if (activeJobId === jobId) return;
    if (activeJobId) {
      console.warn(`[VAHAN EXT] Preempting stale job ${activeJobId} with new job ${jobId}`);
      const staleJobId = activeJobId;
      cancelledJobIds.add(staleJobId);
      const { activeServerJob: staleServerJob } = await chrome.storage.local.get("activeServerJob");
      if (staleServerJob?.jobId === staleJobId) await finishServerJob(staleServerJob);
      else {
        activeJobId = void 0;
        await chrome.storage.local.remove(["pendingServerJob", "activeServerJob"]);
      }
    }
    activeJobId = jobId;
    cancelledJobIds.delete(jobId);
    await chrome.storage.local.set({ pendingServerJob: job });
    chrome.runtime.sendMessage({ type: "SERVER_JOB_ASSIGNED", job }).catch(() => {
    });
    let tabId;
    try {
      await reportJobStatus(jobId, "OPENING_VAHAN");
      tabId = await getVahanTab();
      assertJobActive(jobId);
      const vahanTab = await chrome.tabs.get(tabId);
      vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: Boolean(vahanTab.active) });
      await chrome.storage.local.set({ pendingServerJob: { ...job, tabId } });
      const config = normalizeJobFilters(job.filters);
      await chrome.storage.local.set({
        pendingServerJob: { ...job, tabId },
        activeServerJob: { ...job, tabId, config, stage: "FILLING_FILTERS", executionMode: "background" }
      });
      await reportJobStatus(jobId, "FILLING_FILTERS");
      let fillResponse = await sendToVahan(tabId, { type: "FILL_VAHAN", config });
      if (!fillResponse?.ok && String(fillResponse?.error || "").startsWith("#stateName:")) {
        await chrome.tabs.update(tabId, { url: VAHAN_URL });
        await waitForTabComplete(tabId, INITIAL_PAGE_LOAD_TIMEOUT_MS);
        assertJobActive(jobId);
        fillResponse = await sendToVahan(tabId, { type: "FILL_VAHAN", config });
      }
      if (!fillResponse?.ok) throw new Error(fillResponse?.error || "VAHAN did not accept the filters.");
      assertJobActive(jobId);
      const { vahanConfig = {} } = await chrome.storage.local.get("vahanConfig");
      await chrome.storage.local.set({ vahanConfig: { ...vahanConfig, ...config } });
      await chrome.storage.local.set({
        activeServerJob: { ...job, tabId, config, filtersFilled: true, stage: "CAPTURING_CAPTCHA", executionMode: "background" }
      });
      await reportJobStatus(jobId, "CAPTURING_CAPTCHA");
      const captcha = await sendToVahan(tabId, { type: "CAPTURE_CAPTCHA" });
      if (!captcha?.ok) throw new Error(captcha?.error || "Could not capture the CAPTCHA.");
      assertJobActive(jobId);
      await chrome.storage.local.set({
        activeServerJob: {
          ...job,
          tabId,
          config,
          filtersFilled: true,
          executionMode: "background",
          captchaId: captcha.captchaId,
          stage: "WAITING_CAPTCHA",
          attempts: 0
        }
      });
      await publishCaptcha(jobId, captcha);
    } catch (error) {
      if (!cancelledJobIds.has(jobId)) {
        const authHeld = isVahanAuthHoldActive(vahanAuthHold, Date.now(), tabId);
        if (!(authHeld && authFailureReportedJobs.has(jobId))) {
          let errorMessage2 = error.message;
          if (authHeld) {
            errorMessage2 = `${VAHAN_AUTH_REQUIRED_CODE}: ${vahanAuthHoldMessage(vahanAuthHold)}`;
          } else if (error.code) {
            errorMessage2 = `${error.code}: ${error.message}`;
          }
          await reportJobStatus(
            jobId,
            "FAILED",
            errorMessage2
          ).catch(() => {
          });
          if (authHeld) authFailureReportedJobs.add(jobId);
        }
      }
      await finishServerJob({ jobId, tabId });
    }
  }
  async function loadRunnerConfig() {
    const { runnerConfig = {} } = await chrome.storage.local.get("runnerConfig");
    const normalized = {
      ...DEFAULT_RUNNER_CONFIG,
      ...runnerConfig,
      runnerId: runnerConfig.runnerId || crypto.randomUUID()
    };
    if (JSON.stringify(normalized) !== JSON.stringify(runnerConfig)) {
      await chrome.storage.local.set({ runnerConfig: normalized });
    }
    return normalized;
  }
  async function publishConnection(status, detail = "") {
    const connection = {
      status,
      detail,
      runnerId: activeConfig?.runnerId || null,
      serverUrl: activeConfig?.serverUrl || null,
      updatedAt: (/* @__PURE__ */ new Date()).toISOString()
    };
    await chrome.storage.local.set({ runnerConnection: connection });
    chrome.runtime.sendMessage({ type: "RUNNER_CONNECTION_CHANGED", connection }).catch(() => {
    });
  }
  function stopHeartbeat() {
    clearInterval(heartbeatTimer);
    heartbeatTimer = void 0;
  }
  function startHeartbeat() {
    stopHeartbeat();
    heartbeatTimer = setInterval(() => {
      if (!socket?.connected) return;
      socket.timeout(5e3).emit("runner:heartbeat", { timestamp: Date.now() }, (error, response) => {
        if (error || !response?.ok) {
          const detail = error?.message || response?.error || "Heartbeat failed.";
          publishConnection("error", detail);
          if (!error && response?.ok === false && /not registered/i.test(response.error || "")) {
            void connectRunner({ force: true }).catch(() => {
            });
          }
        }
      });
    }, HEARTBEAT_INTERVAL_MS);
  }
  async function connectRunnerOnce() {
    clearTimeout(reconnectTimer);
    activeConfig = await loadRunnerConfig();
    void uiHealthCheckController?.refreshScheduleFromBackend();
    socket?.removeAllListeners();
    socket?.disconnect();
    await publishConnection("connecting", "Connecting to backend...");
    socket = lookup2(`${activeConfig.serverUrl}/runner`, {
      transports: ["websocket"],
      auth: {
        runnerId: activeConfig.runnerId,
        runnerName: activeConfig.runnerName,
        source: "new",
        token: activeConfig.token,
        version: chrome.runtime.getManifest().version
      },
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1e3,
      reconnectionDelayMax: 1e4,
      timeout: 1e4
    });
    socket.on("connect", async () => {
      publishConnection("connected", "Backend connected.");
      startHeartbeat();
      await flushPendingSuccessfulApplyClicks();
      const { activeServerJob, pendingServerJob } = await chrome.storage.local.get([
        "activeServerJob",
        "pendingServerJob"
      ]);
      if (activeServerJob?.jobId) {
        if (activeJobId === activeServerJob.jobId && !cancelledJobIds.has(activeJobId)) return;
        await reportJobStatus(activeServerJob.jobId, "FAILED", "Extension reconnected or restarted.").catch(() => {
        });
        await restorePreviousJobTab(activeServerJob);
      } else if (pendingServerJob?.jobId) {
        if (activeJobId === pendingServerJob.jobId && !cancelledJobIds.has(activeJobId)) return;
        await restorePreviousJobTab(pendingServerJob);
      }
      activeJobId = void 0;
      await chrome.storage.local.remove(["pendingServerJob", "activeServerJob"]);
    });
    socket.on("disconnect", (reason) => {
      stopHeartbeat();
      publishConnection("disconnected", `Disconnected: ${reason}`);
    });
    socket.on("connect_error", (error) => {
      stopHeartbeat();
      publishConnection("error", error.message || "Could not connect to backend.");
    });
    socket.on("ui-health:schedule-updated", (schedule) => {
      uiHealthCheckController?.updateSchedule(schedule?.intervalDays).catch((error) => {
        console.warn("[VAHAN UI HEALTH] Could not update the check schedule:", error.message);
      });
    });
    socket.on("ui-health:run-now", (request = {}) => {
      uiHealthCheckController?.run("manual-web").then((healthCheck) => {
        console.info(
          "[VAHAN UI HEALTH] Immediate official-tab check completed:",
          request.requestId || "unknown-request",
          healthCheck.status
        );
      }).catch((error) => {
        console.warn("[VAHAN UI HEALTH] Immediate check failed:", error.message);
      });
    });
    socket.io.on("reconnect_attempt", () => {
      publishConnection("connecting", "Reconnecting to backend...");
    });
    socket.on("job:assigned", (job) => executeJob(job).catch(async (error) => {
      const jobId = String(job?.jobId || "");
      if (jobId) await reportJobStatus(jobId, "FAILED", error.message).catch(() => {
      });
      if (activeJobId === jobId) activeJobId = void 0;
    }));
    socket.on("job:cancelled", async ({ jobId }) => {
      const id = String(jobId);
      cancelledJobIds.add(id);
      if (pendingBlobResolver) pendingBlobResolver(null);
      pendingReportUploadController?.abort();
      const { activeServerJob, pendingServerJob } = await chrome.storage.local.get([
        "activeServerJob",
        "pendingServerJob"
      ]);
      if (activeServerJob?.jobId === id) await finishServerJob(activeServerJob);
      else if (pendingServerJob?.jobId === id) {
        await restorePreviousJobTab(pendingServerJob);
        await chrome.storage.local.remove("pendingServerJob");
      }
      if (activeJobId === id) activeJobId = void 0;
    });
    socket.on("captcha:submit", async (payload, acknowledge) => {
      const jobId = String(payload?.jobId || "");
      let activeServerJob;
      try {
        ({ activeServerJob } = await chrome.storage.local.get("activeServerJob"));
        if (!activeServerJob || activeServerJob.jobId !== jobId || activeServerJob.stage !== "WAITING_CAPTCHA" || activeJobId && activeJobId !== jobId) {
          throw new Error("The active VAHAN job no longer matches this CAPTCHA.");
        }
        activeJobId = jobId;
        if (activeServerJob.captchaId !== payload.captchaId) {
          throw new Error("The CAPTCHA has changed or expired.");
        }
        assertJobActive(jobId);
        const attempts = (activeServerJob.attempts || 0) + 1;
        await chrome.storage.local.set({
          activeServerJob: {
            ...activeServerJob,
            stage: "SUBMITTING",
            attempts
          }
        });
        if (!activeServerJob.filtersFilled) throw new Error("VAHAN filters are not ready yet.");
        assertJobActive(jobId);
        const currentCaptcha = await sendToVahan(activeServerJob.tabId, { type: "CAPTURE_CAPTCHA" });
        if (!currentCaptcha?.ok) {
          throw new Error(currentCaptcha?.error || "Could not verify the current CAPTCHA.");
        }
        if (currentCaptcha.captchaId !== activeServerJob.captchaId) {
          await chrome.storage.local.set({
            activeServerJob: {
              ...activeServerJob,
              captchaId: currentCaptcha.captchaId,
              stage: "WAITING_CAPTCHA",
              attempts: attempts - 1
            }
          });
          await reportJobStatus(jobId, "WAITING_CAPTCHA");
          await publishCaptcha(jobId, currentCaptcha);
          acknowledge({ ok: true, refreshed: true });
          return;
        }
        const response = await sendToVahan(activeServerJob.tabId, {
          type: "SUBMIT_REMOTE_CAPTCHA",
          value: String(payload.value || ""),
          autoApply: activeServerJob.config.autoApply ?? false
        });
        if (!response?.ok) throw new Error(response?.error || "Could not fill the CAPTCHA on VAHAN.");
        await chrome.storage.local.set({
          activeServerJob: {
            ...activeServerJob,
            stage: "WAITING_RESULT",
            attempts
          }
        });
        await reportJobStatus(jobId, "WAITING_RESULT");
        acknowledge({ ok: true });
      } catch (error) {
        await reportJobStatus(jobId, "FAILED", error.message).catch(() => {
        });
        if (activeServerJob?.jobId === jobId) await finishServerJob(activeServerJob);
        acknowledge({ ok: false, error: error.message });
      }
    });
    socket.on("captcha:refresh", async (payload, acknowledge) => {
      const jobId = String(payload?.jobId || "");
      try {
        const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
        if (!activeServerJob || activeServerJob.jobId !== jobId || activeServerJob.stage !== "WAITING_CAPTCHA") {
          throw new Error("The job is not waiting for a CAPTCHA refresh.");
        }
        if (activeServerJob.captchaId !== payload?.captchaId) {
          throw new Error("The CAPTCHA has changed or expired.");
        }
        assertJobActive(jobId);
        const captcha = await requestFreshCaptcha(activeServerJob);
        await publishCaptchaChange(activeServerJob, captcha, "captcha:refreshed");
        acknowledge({ ok: true, captcha: {
          jobId,
          captchaId: captcha.captchaId,
          imageDataUrl: captcha.imageDataUrl
        } });
      } catch (error) {
        acknowledge({ ok: false, error: error.message });
      }
    });
    socket.on("runner:options", async (request, acknowledge) => {
      try {
        const tabId = await getOptionsTab();
        const messageByType = {
          GET_ALL_OPTIONS: {
            type: "GET_VAHAN_OPTIONS",
            selectors: VAHAN_OPTION_SELECTORS
          },
          GET_STATE_OPTIONS: { type: "GET_STATE_OPTIONS", delhiNcr: request.delhiNcr },
          GET_RTO_OPTIONS: { type: "GET_RTO_OPTIONS", stateLabels: request.stateLabels },
          GET_X_AXIS_OPTIONS: { type: "GET_X_AXIS_OPTIONS", yAxis: request.yAxis },
          SEARCH_MAKERS: { type: "SEARCH_MAKERS", search: request.search }
        };
        const message = messageByType[request.type];
        if (!message) throw new Error("Unsupported VAHAN options request.");
        acknowledge(await sendToVahan(tabId, message));
      } catch (error) {
        acknowledge({ ok: false, error: error.message });
      }
    });
  }
  function connectRunner({ force = false } = {}) {
    if (runnerConnectionTask) {
      runnerReconnectRequested ||= force;
      return runnerConnectionTask;
    }
    const task = (async () => {
      do {
        runnerReconnectRequested = false;
        await connectRunnerOnce();
      } while (runnerReconnectRequested);
    })().catch(async (error) => {
      stopHeartbeat();
      await publishConnection("error", error?.message || "Could not start the backend connection.").catch(() => {
      });
      throw error;
    }).finally(() => {
      if (runnerConnectionTask === task) runnerConnectionTask = void 0;
    });
    runnerConnectionTask = task;
    return task;
  }
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name !== RUNNER_CONNECTION_ALARM || socket?.active) return;
    void connectRunner().catch(() => {
    });
  });
  chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === "loading") {
      vahanPageHeartbeats.delete(tabId);
      vahanPageLivenessProbes.delete(tabId);
      return;
    }
    if (changeInfo.status === "complete" && isVahanPublicReportUrl(tab.url)) {
      vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: Boolean(tab.active) });
    }
  });
  function refreshVahanHeartbeatAfterFocus(tabId) {
    chrome.tabs.get(tabId).then((tab) => {
      if (isVahanPublicReportUrl(tab.url)) {
        vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: true });
      }
    }).catch(() => {
    });
  }
  chrome.tabs.onActivated.addListener(({ tabId }) => refreshVahanHeartbeatAfterFocus(tabId));
  chrome.windows.onFocusChanged.addListener((windowId) => {
    if (windowId === chrome.windows.WINDOW_ID_NONE) return;
    chrome.tabs.query({ active: true, windowId }).then((tabs) => {
      const tab = tabs[0];
      if (tab?.id && isVahanPublicReportUrl(tab.url)) {
        vahanPageHeartbeats.set(tab.id, { receivedAt: Date.now(), visible: true });
      }
    }).catch(() => {
    });
  });
  async function handlePageResult(message, sender) {
    const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
    if (!activeServerJob || activeServerJob.stage === "PAGE_STALLED_RELOADING" || activeJobId && activeServerJob.jobId !== activeJobId) return;
    if (!matchesJobPageResult(message, sender, activeServerJob)) return;
    activeJobId = activeServerJob.jobId;
    if (sender.tab?.id !== activeServerJob.tabId) return;
    const jobId = activeServerJob.jobId;
    if (message.result === "AUTH_REQUIRED") {
      const hold = vahanAuthHold || await loadVahanAuthHold();
      await reportJobStatus(
        jobId,
        "FAILED",
        `${VAHAN_AUTH_REQUIRED_CODE}: ${vahanAuthHoldMessage(hold || {})}`
      ).catch(() => {
      });
      await finishServerJob(activeServerJob);
      return;
    }
    if (message.result === "INVALID_CAPTCHA") {
      if ((activeServerJob.attempts || 0) >= 3) {
        await reportJobStatus(jobId, "FAILED", "CAPTCHA was invalid 3 consecutive times.").catch(() => {
        });
        await finishServerJob(activeServerJob);
        return;
      }
      let captcha = message.captcha;
      if (!captcha?.captchaId || !captcha?.imageDataUrl || captcha.captchaId === activeServerJob.captchaId) {
        captcha = await requestFreshCaptcha(activeServerJob);
      }
      await publishCaptchaChange(activeServerJob, captcha, "captcha:invalid");
      return;
    }
    if (message.result === "DOWNLOAD_READY") {
      if (reportJobInFlight === jobId || ["DOWNLOADING_REPORT", "UPLOADING_REPORT"].includes(activeServerJob.stage)) return;
      reportJobInFlight = jobId;
      try {
        assertJobActive(jobId);
        await chrome.storage.local.set({
          activeServerJob: { ...activeServerJob, stage: "DOWNLOADING_REPORT" }
        });
        await triggerAndWaitForExcelDownload(activeServerJob);
        assertJobActive(jobId);
        await emitWithRetry("job:status", { jobId, status: "COMPLETED" });
      } catch (error) {
        if (!cancelledJobIds.has(jobId)) {
          await reportJobStatus(jobId, "FAILED", error.message).catch(() => {
          });
        }
      } finally {
        if (reportJobInFlight === jobId) reportJobInFlight = void 0;
      }
      await finishServerJob(activeServerJob);
      return;
    }
    if (message.result === "COMPLETED") {
      await reportJobStatus(jobId, "FAILED", "The page did not provide a captured Excel report.").catch(() => {
      });
      await finishServerJob(activeServerJob);
      return;
    }
    if (message.result === "NO_RECORD") {
      await reportJobStatus(jobId, "NO_DATA");
      await finishServerJob(activeServerJob);
      return;
    }
    if (message.result === "FAILED") {
      await reportJobStatus(jobId, "FAILED", message.error || "VAHAN did not return a result.").catch(() => {
      });
      await finishServerJob(activeServerJob);
    }
  }
  async function handleCaptchaChanged(message, sender) {
    const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
    if (!activeServerJob || activeServerJob.stage !== "WAITING_CAPTCHA") return;
    if (sender.tab?.id !== activeServerJob.tabId) return;
    const captcha = message.captcha;
    if (!captcha?.captchaId || !captcha?.imageDataUrl || captcha.captchaId === activeServerJob.captchaId) return;
    await publishCaptchaChange(activeServerJob, captcha, "captcha:refreshed");
  }
  chrome.runtime.onInstalled.addListener(() => {
    void connectRunner().catch(() => {
    });
  });
  chrome.runtime.onStartup.addListener(() => {
    void connectRunner().catch(() => {
    });
  });
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local" || !changes.runnerConfig) return;
    const nextConfig = changes.runnerConfig.newValue;
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      if (JSON.stringify(nextConfig) !== JSON.stringify(activeConfig)) {
        void connectRunner({ force: true }).catch(() => {
        });
      }
    }, 250);
  });
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type === "VAHAN_PAGE_HEARTBEAT") {
      const tabId = sender?.tab?.id;
      if (sender?.id !== chrome.runtime.id || !Number.isInteger(tabId) || !isVahanPublicReportUrl(sender.url) || typeof message.visible !== "boolean") {
        sendResponse({ ok: false, error: "Invalid VAHAN page heartbeat." });
        return;
      }
      vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: message.visible });
      sendResponse({ ok: true });
      return;
    }
    if (message?.type === "COUNT_SUCCESSFUL_APPLY_CLICK") {
      if (!isVahanPublicReportUrl(sender?.url) || typeof message.clickId !== "string" || !message.clickId) {
        sendResponse({ ok: false, error: "Invalid VAHAN Apply click." });
        return;
      }
      Promise.all([
        recordSuccessfulApplyClick(message.clickId),
        chrome.storage.local.get("activeServerJob")
      ]).then(async ([{ count, duplicate }, { activeServerJob }]) => {
        const jobId = typeof activeServerJob?.jobId === "string" ? activeServerJob.jobId : "";
        const serverRecorded = jobId ? await queueSuccessfulApplyClickForJob(jobId, message.clickId).catch(() => false) : null;
        sendResponse({ ok: true, count, duplicate, serverRecorded });
      }).catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "RESET_SUCCESSFUL_APPLY_COUNT") {
      resetSuccessfulApplyCount().then(({ count }) => sendResponse({ ok: true, count })).catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "SERVER_CAPTCHA_CHANGED") {
      handleCaptchaChanged(message, sender).then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "EXCEL_BLOB_CAPTURED") {
      if (!matchesReportCapture(message, sender, pendingReportCapture)) {
        sendResponse({ ok: false, error: "Excel capture does not match the active report." });
        return;
      }
      if (pendingBlobResolver) {
        pendingBlobResolver({ dataUrl: message.dataUrl, fileName: message.fileName });
      }
      sendResponse({ ok: true });
      return true;
    }
    if (message?.type === "EXCEL_BLOB_FAILED") {
      if (!matchesReportCapture(message, sender, pendingReportCapture)) {
        sendResponse({ ok: false, error: "Excel capture does not match the active report." });
        return;
      }
      if (pendingBlobResolver) pendingBlobResolver({ error: message.error });
      sendResponse({ ok: true });
      return true;
    }
    if (message?.type === "SERVER_JOB_PAGE_RESULT") {
      handlePageResult(message, sender).then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "OPEN_ACTION_POPUP") {
      if (typeof chrome.action.openPopup !== "function") {
        sendResponse({ ok: false, error: "This feature requires Google Chrome 127 or later." });
        return;
      }
      chrome.action.openPopup().then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "GET_RUNNER_CONNECTION") {
      chrome.storage.local.get("runnerConnection").then(({ runnerConnection }) => {
        sendResponse({ ok: true, connection: runnerConnection || { status: "disconnected" } });
      });
      return true;
    }
    if (message?.type === "GET_VAHAN_AUTH_HOLD") {
      (async () => {
        const hold = vahanAuthHold || await loadVahanAuthHold();
        sendResponse({ ok: true, authHold: isVahanAuthHoldActive(hold) ? hold : null });
      })().catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "CLEAR_VAHAN_AUTH_HOLD") {
      clearVahanAuthHold().then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "RELOAD_VAHAN_PAGE") {
      (async () => {
        await clearVahanAuthHold();
        const tabs = await chrome.tabs.query({ url: "https://analytics.parivahan.gov.in/*" });
        if (tabs[0]?.id) {
          await chrome.tabs.update(tabs[0].id, { url: VAHAN_URL });
          return { ok: true };
        }
        await chrome.tabs.create({ url: VAHAN_URL });
        return { ok: true };
      })().then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "RECONNECT_RUNNER") {
      connectRunner({ force: true }).then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
  });
  startVahanPageStallWatchdog();
  uiHealthCheckController = registerUiHealthCheck(chrome);
  installVahanAuthGuard();
  void loadVahanAuthHold();
  chrome.alarms.create(RUNNER_CONNECTION_ALARM, { periodInMinutes: 0.5 });
  void connectRunner().catch(() => {
  });
})();
