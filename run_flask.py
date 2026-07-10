# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "export"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import app as app_module
app_module.app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
