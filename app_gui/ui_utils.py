# EasyAISubbing/app_gui/ui_utils.py
import tkinter as tk
from tkinter import ttk, font as tkFont # Added ttk for consistency if needed

class ToolTip(object):
    def __init__(self, widget, text='widget info', wraplength=300):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.tooltip_window = None
        self.id = None
        self.x = self.y = 0
        self._bind()

    def _bind(self):
        self.widget.bind("<Enter>", self.enter, add="+")
        self.widget.bind("<Leave>", self.leave, add="+")
        self.widget.bind("<ButtonPress>", self.leave, add="+")

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(700, self.showtip)

    def unschedule(self):
        id_val = self.id
        self.id = None
        if id_val:
            self.widget.after_cancel(id_val)

    def showtip(self, event=None):
        if self.tooltip_window or not self.text:
            return

        x = self.widget.winfo_pointerx() + 20
        y = self.widget.winfo_pointery() + 15

        screen_width = self.widget.winfo_screenwidth()
        screen_height = self.widget.winfo_screenheight()

        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)

        label = tk.Label(tw, text=self.text, justify='left',
                         background="#ffffe0", relief='solid', borderwidth=1,
                         font=("tahoma", "8", "normal"),
                         wraplength=self.wraplength)
        label.pack(ipadx=2, ipady=2)

        tw.update_idletasks()
        width = tw.winfo_width()
        height = tw.winfo_height()

        if x + width > screen_width:
            x = screen_width - width - 5
        if y + height > screen_height:
            y = screen_height - height - 5

        tw.wm_geometry(f"+{int(x)}+{int(y)}")

    def hidetip(self):
        tw = self.tooltip_window
        self.tooltip_window = None
        if tw:
            try:
                tw.destroy()
            except tk.TclError:
                pass

def show_scrollable_messagebox(parent_window, title, message, default_font_family="Segoe UI", default_font_size=10):
    """
    Displays a scrollable message box.
    parent_window: The parent window (tk.Tk or tk.Toplevel) for modality.
    """
    top = tk.Toplevel(parent_window)
    top.title(title)

    # Attempt to make it modal and centered relative to the parent
    top.transient(parent_window)
    top.grab_set()

    num_lines = message.count('\n')
    width_chars = 85
    text_width_calc = 0
    if message:
        lines_for_width_calc = [line for line in message.split('\n') if line.strip()]
        if lines_for_width_calc:
             text_width_calc = max(len(line) for line in lines_for_width_calc) + 5 # Add some padding
    text_width = min(width_chars, text_width_calc if text_width_calc > 5 else width_chars )

    # Use a temporary font object to measure characters and lines for sizing
    temp_font = tkFont.Font(family=default_font_family, size=default_font_size -1) # Slightly smaller for messagebox
    avg_char_width = temp_font.measure("0")
    width_pixels = int(text_width * avg_char_width * 0.95) # Adjust multiplier as needed
    width_pixels = max(450, min(width_pixels, parent_window.winfo_screenwidth() // 2))

    height_lines = min(30, num_lines + 6) # Add a bit more for padding and button
    avg_line_height = temp_font.metrics("linespace")
    height_pixels = int(height_lines * avg_line_height * 1.15) # Adjust multiplier
    height_pixels = max(250, min(height_pixels, parent_window.winfo_screenheight() // 2))

    # Center on parent
    parent_x = parent_window.winfo_x()
    parent_y = parent_window.winfo_y()
    parent_width = parent_window.winfo_width()
    parent_height = parent_window.winfo_height()

    x_pos = parent_x + (parent_width // 2) - (width_pixels // 2)
    y_pos = parent_y + (parent_height // 2) - (height_pixels // 2)
    top.geometry(f"{width_pixels}x{height_pixels}+{max(0,x_pos)}+{max(0,y_pos)}")
    top.minsize(300, 150) # Minimum reasonable size

    txt_frame = ttk.Frame(top)
    txt_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10,5)) # Add padding

    txt = tk.Text(txt_frame, wrap=tk.WORD, font=temp_font, relief=tk.SOLID, borderwidth=1,
                  padx=5, pady=5) # Add internal padding to text widget
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    scrollbar = ttk.Scrollbar(txt_frame, orient=tk.VERTICAL, command=txt.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    txt.config(yscrollcommand=scrollbar.set)

    txt.insert(tk.END, message)
    txt.config(state="disabled") # Make it read-only

    button_frame = ttk.Frame(top)
    button_frame.pack(fill=tk.X, pady=(5,10)) # Add padding

    # Use a default style if Accent.TButton is not available in the current theme
    ok_button_style = "Accent.TButton" if "Accent.TButton" in ttk.Style().theme_names() and "Accent.TButton" in ttk.Style().layout("Accent.TButton") else "TButton"

    ok_button = ttk.Button(button_frame, text="OK", command=top.destroy, style=ok_button_style)
    ok_button.pack(pady=5) # Add padding around button

    parent_window.wait_window(top) # Wait for this dialog to close before parent can be interacted with