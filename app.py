# CustomTkinter desktop shell for Shopify AI Store Manager.

from __future__ import annotations

import queue
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from shopify_agent.ai_agent import StoreAgent
from shopify_agent.config import AppConfig, SettingsStore
from shopify_agent.shopify_client import ShopifyClient


BG = "#10131a"
PANEL = "#191e29"
ACCENT = "#7c5cff"
MUTED = "#9aa4b2"
TEXT = "#f2f4f8"


class StoreManagerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Shopify AI Store Manager")
        self.geometry("1240x820")
        self.minsize(980, 680)
        self.configure(fg_color=BG)
        self.settings = SettingsStore()
        self.config = self.settings.load()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="store-agent")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._closing = False
        self._config_widgets: dict[str, ctk.CTkEntry] = {}
        self._secret_widgets: dict[str, ctk.CTkEntry] = {}
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color=BG)
        header.pack(fill="x", padx=28, pady=(22, 8))
        ctk.CTkLabel(header, text="STORE MANAGER", text_color=ACCENT,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Your Shopify operations, in one place",
                     text_color=TEXT, font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(header, text="Gemini assistant  •  Shopify Admin  •  Local credential vault",
                     text_color=MUTED, font=ctk.CTkFont(size=13)).pack(anchor="w", pady=(5, 4))

        self.tabs = ctk.CTkTabview(self, fg_color=BG, segmented_button_selected_color=ACCENT,
                                  segmented_button_selected_hover_color="#6646e8")
        self.tabs.pack(fill="both", expand=True, padx=24, pady=(8, 22))
        self.dashboard = self.tabs.add("Dashboard")
        self.settings_tab = self.tabs.add("Settings")
        self._build_dashboard()
        self._build_settings()

    def _build_dashboard(self) -> None:
        self.dashboard.grid_columnconfigure(0, weight=3)
        self.dashboard.grid_columnconfigure(1, weight=2)
        self.dashboard.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(self.dashboard, fg_color=PANEL, corner_radius=16)
        right = ctk.CTkFrame(self.dashboard, fg_color=PANEL, corner_radius=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=8)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        title_row = ctk.CTkFrame(left, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=18, pady=(17, 8))
        ctk.CTkLabel(title_row, text="Activity", text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight="bold")).pack(side="left")
        self.activity = ctk.CTkTextbox(left, fg_color="#11151d", text_color="#d2d9e3",
                                       corner_radius=12, wrap="word", font=ctk.CTkFont(size=12))
        self.activity.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))
        self.activity.configure(state="disabled")
        command_frame = ctk.CTkFrame(left, fg_color="transparent")
        command_frame.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        command_frame.grid_columnconfigure(0, weight=1)
        self.command_entry = ctk.CTkEntry(command_frame, placeholder_text="Ask the agent to help manage your store…",
                                          height=42, fg_color="#11151d", border_color="#303848")
        self.command_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.command_entry.bind("<Return>", lambda _event: self._send_command())
        self.send_button = ctk.CTkButton(command_frame, text="Run", width=90, height=42,
                                         fg_color=ACCENT, command=self._send_command)
        self.send_button.grid(row=0, column=1)

        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        order_header = ctk.CTkFrame(right, fg_color="transparent")
        order_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(17, 9))
        ctk.CTkLabel(order_header, text="Recent orders", text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight="bold")).pack(side="left")
        ctk.CTkButton(order_header, text="Refresh", width=78, height=30, fg_color="#293143",
                      hover_color="#35415a", command=self._refresh_orders).pack(side="right")
        self.orders_list = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.orders_list.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._render_orders([])
        self._log("Ready. Save your API credentials in Settings to begin.")

    def _render_orders(self, orders: list) -> None:
        for child in self.orders_list.winfo_children():
            child.destroy()
        if not orders:
            ctk.CTkLabel(self.orders_list, text="No orders loaded yet.\nChoose Refresh to fetch recent orders.",
                         text_color=MUTED, justify="left").pack(anchor="w", padx=8, pady=12)
            return
        for order in orders:
            card = ctk.CTkFrame(self.orders_list, fg_color="#202634", corner_radius=11)
            card.pack(fill="x", padx=3, pady=5)
            ctk.CTkLabel(card, text=order.name, text_color=TEXT,
                         font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(9, 0))
            ctk.CTkLabel(card, text=f"{order.customer}   ·   {order.total} {order.currency}",
                         text_color="#c2cad5", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(4, 0))
            ctk.CTkLabel(card, text=f"{order.created_at[:16].replace('T', ' ')}   ·   {order.financial_status}",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(3, 9))

    def _build_settings(self) -> None:
        self.settings_tab.grid_columnconfigure(0, weight=1)
        self.settings_tab.grid_columnconfigure(1, weight=1)
        self.settings_tab.grid_rowconfigure(0, weight=1)
        left = ctk.CTkScrollableFrame(self.settings_tab, fg_color=PANEL, corner_radius=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9), pady=8)
        right = ctk.CTkScrollableFrame(self.settings_tab, fg_color=PANEL, corner_radius=16)
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 0), pady=8)
        ctk.CTkLabel(left, text="Store and AI", text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=18, pady=(18, 12))
        self._add_field(left, "Gemini API key", "gemini_api_key", secret=True)
        self._add_field(left, "Gemini model", "gemini_model", value=self.config.gemini_model)
        self._add_field(left, "Shopify store URL", "store_url", value=self.config.store_url,
                        placeholder="https://your-store.myshopify.com")
        self._add_field(left, "Shopify Admin API token", "shopify_admin_api_token", secret=True)
        self._add_field(left, "Shopify API version", "shopify_api_version", value=self.config.shopify_api_version)
        self._add_field(left, "WhatsApp destination number", "whatsapp_number", secret=True,
                        placeholder="International format, e.g. +15551234567")
        self._add_field(left, "WhatsApp sender Phone Number ID", "whatsapp_phone_number_id",
                        value=self.config.whatsapp_phone_number_id)
        self._add_field(left, "WhatsApp Cloud API token", "whatsapp_cloud_api_token", secret=True)
        self._add_field(left, "WhatsApp Graph API version", "whatsapp_graph_api_version",
                        value=self.config.whatsapp_graph_api_version)
        self._add_field(left, "Optional approved message template", "whatsapp_template_name",
                        value=self.config.whatsapp_template_name)
        self._add_field(left, "Template language", "whatsapp_template_language",
                        value=self.config.whatsapp_template_language)

        ctk.CTkLabel(right, text="Email and safeguards", text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=18, pady=(18, 12))
        self._add_field(right, "SMTP server", "smtp_host", value=self.config.smtp_host)
        self._add_field(right, "SMTP port", "smtp_port", value=str(self.config.smtp_port))
        self._add_field(right, "SMTP username", "smtp_username", secret=True)
        self._add_field(right, "SMTP password", "smtp_password", secret=True)
        self._add_field(right, "From email address", "smtp_from_email", value=self.config.smtp_from_email)
        self.confirm_switch = ctk.CTkSwitch(
            right, text="Confirm product creation and outbound email",
            progress_color=ACCENT, text_color=TEXT,
        )
        self.confirm_switch.pack(anchor="w", padx=18, pady=(20, 6))
        if self.config.require_confirmation:
            self.confirm_switch.select()
        ctk.CTkLabel(right, text="Credentials are stored in the OS credential manager. Leave a secret field blank to keep its saved value.",
                     text_color=MUTED, wraplength=420, justify="left").pack(anchor="w", padx=18, pady=(4, 12))
        ctk.CTkButton(right, text="Save settings", height=42, fg_color=ACCENT,
                      command=self._save_settings).pack(fill="x", padx=18, pady=(6, 18))

    def _add_field(self, parent, label: str, key: str, *, value: str = "", secret: bool = False,
                   placeholder: str = "") -> None:
        group = ctk.CTkFrame(parent, fg_color="transparent")
        group.pack(fill="x", padx=18, pady=5)
        ctk.CTkLabel(group, text=label, text_color="#c7cfda",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 4))
        entry = ctk.CTkEntry(group, height=36, fg_color="#11151d", border_color="#303848",
                             placeholder_text=placeholder or ("Saved securely · leave blank to keep" if secret else ""),
                             show="•" if secret else "")
        if value:
            entry.insert(0, str(value))
        entry.pack(fill="x")
        if secret:
            self._secret_widgets[key] = entry
        else:
            self._config_widgets[key] = entry

    def _save_settings(self) -> None:
        try:
            port_text = self._config_widgets["smtp_port"].get().strip() or "587"
            port = int(port_text)
            if not 1 <= port <= 65535:
                raise ValueError("SMTP port must be between 1 and 65535.")
            config = AppConfig(
                store_url=self._config_widgets["store_url"].get().strip(),
                smtp_host=self._config_widgets["smtp_host"].get().strip(),
                smtp_port=port,
                smtp_from_email=self._config_widgets["smtp_from_email"].get().strip(),
                gemini_model=self._config_widgets["gemini_model"].get().strip() or "gemini-3.8-flash",
                shopify_api_version=self._config_widgets["shopify_api_version"].get().strip() or "2026-10",
                whatsapp_graph_api_version=self._config_widgets["whatsapp_graph_api_version"].get().strip() or "v23.0",
                whatsapp_phone_number_id=self._config_widgets["whatsapp_phone_number_id"].get().strip(),
                whatsapp_template_name=self._config_widgets["whatsapp_template_name"].get().strip(),
                whatsapp_template_language=self._config_widgets["whatsapp_template_language"].get().strip() or "en_US",
                require_confirmation=bool(self.confirm_switch.get()),
            )
            self.settings.save(config)
            for key, entry in self._secret_widgets.items():
                secret_value = entry.get()
                if secret_value:
                    self.settings.set_secret(key, secret_value)
                    entry.delete(0, "end")
            self.config = config
            self._log("Settings saved. Secret values were written to the OS credential manager.")
            messagebox.showinfo("Settings saved", "Settings and credentials were saved securely.")
        except Exception as exc:
            messagebox.showerror("Could not save settings", str(exc))

    def _send_command(self) -> None:
        command = self.command_entry.get().strip()
        if not command:
            return
        self.command_entry.delete(0, "end")
        self._log(f"You: {command}")
        self.send_button.configure(state="disabled", text="Working…")
        self._submit("agent", lambda: self._run_agent(command))

    def _run_agent(self, command: str) -> str:
        config = self.settings.load()
        agent = StoreAgent(config, self.settings, self._ask_approval,
                           log_callback=lambda text: self.events.put(("log", text)))
        return agent.run(command)

    def _refresh_orders(self) -> None:
        self._log("Loading recent Shopify orders…")
        self._submit("orders", self._load_orders)

    def _load_orders(self) -> list:
        config = self.settings.load()
        token = self.settings.get_secret("shopify_admin_api_token")
        return ShopifyClient(config, token).recent_orders()

    def _ask_approval(self, description: str) -> bool:
        """Ask from the Tk thread while a worker waits for the user's decision."""
        future: Future = Future()
        def show_prompt() -> None:
            if self._closing:
                future.set_result(False)
                return
            future.set_result(messagebox.askyesno("Confirm store action", description, parent=self))
        self.after(0, show_prompt)
        try:
            return bool(future.result(timeout=300))
        except Exception:
            return False

    def _submit(self, event_name: str, task: Callable):
        future = self.executor.submit(task)
        def completed(done_future: Future) -> None:
            try:
                result = done_future.result()
                self.events.put((event_name, result))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        future.add_done_callback(completed)

    def _drain_events(self) -> None:
        try:
            while True:
                name, value = self.events.get_nowait()
                if name == "log":
                    self._log(str(value))
                elif name == "agent":
                    self._log(f"Assistant: {value}")
                    self.send_button.configure(state="normal", text="Run")
                elif name == "orders":
                    self._render_orders(value)
                    self._log(f"Loaded {len(value)} recent order(s).")
                elif name == "error":
                    self._log(f"Error: {value}")
                    self.send_button.configure(state="normal", text="Run")
                    messagebox.showerror("Operation failed", str(value))
        except queue.Empty:
            pass
        if not self._closing:
            self.after(120, self._drain_events)

    def _log(self, text: str) -> None:
        if not hasattr(self, "activity"):
            return
        self.activity.configure(state="normal")
        self.activity.insert("end", f"{text}\n")
        self.activity.see("end")
        self.activity.configure(state="disabled")

    def _on_close(self) -> None:
        self._closing = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


if __name__ == "__main__":
    StoreManagerApp().mainloop()

