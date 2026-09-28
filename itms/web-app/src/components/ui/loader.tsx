import { motion } from "framer-motion";

export function LoaderOne() {
  return (
    <div className="relative flex h-32 w-32 items-center justify-center">
      {/* Outer spinning dashed ring */}
      <motion.div
        className="absolute inset-0 rounded-full border border-dashed border-[#3fe0ff]/40"
        animate={{ rotate: 360 }}
        transition={{ duration: 10, repeat: Infinity, ease: "linear" }}
      />
      
      {/* Middle spinning segmented ring */}
      <motion.div
        className="absolute inset-3 rounded-full border-2 border-t-[#3fe0ff] border-r-transparent border-b-[#3fe0ff]/20 border-l-transparent"
        animate={{ rotate: -360 }}
        transition={{ duration: 2.5, repeat: Infinity, ease: "linear" }}
      />

      {/* Inner fast ring */}
      <motion.div
        className="absolute inset-6 rounded-full border-[1.5px] border-l-[#3fe0ff] border-r-transparent border-t-transparent border-b-transparent"
        animate={{ rotate: 360 }}
        transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
      />
      
      {/* Pulsing center core */}
      <motion.div
        className="h-3 w-3 rounded-full bg-[#3fe0ff]"
        animate={{ scale: [1, 1.8, 1], opacity: [0.4, 1, 0.4] }}
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        style={{ boxShadow: "0 0 15px 4px rgba(63,224,255,0.6)" }}
      />
    </div>
  );
}
