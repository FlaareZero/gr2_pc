// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <atomic>
#include <cstdio>
#include <unordered_map>

#include "common/hash.h"
#include "common/logging/classes.h"
#include "shader_recompiler/frontend/control_flow_graph.h"
#include "shader_recompiler/frontend/decode.h"
#include "shader_recompiler/frontend/structured_control_flow.h"
#include "shader_recompiler/frontend/translate/translate.h"
#include "shader_recompiler/ir/passes/ir_passes.h"
#include "shader_recompiler/ir/post_order.h"
#include "shader_recompiler/ir/program.h"
#include "shader_recompiler/profile.h"
#include "shader_recompiler/recompiler.h"

namespace Shader {

// Local exact common-subexpression elimination for the GPU vertex/geometry
// and fragment execution paths. Only pure ALU and vector construction ops
// are allowed; no memory operations, interpolation, derivatives, exports,
// texture sampling, subgroup ops or stateful instructions are touched.
// Identical operands, flags and definitions are required; no reordering or
// cross-basic-block code motion takes place.
namespace {
bool IsGraphicsPureArithmetic(IR::Opcode opcode) {
    switch (opcode) {
    case IR::Opcode::IAdd32:
    case IR::Opcode::ISub32:
    case IR::Opcode::IMul32:
    case IR::Opcode::ShiftLeftLogical32:
    case IR::Opcode::ShiftRightLogical32:
    case IR::Opcode::ShiftRightArithmetic32:
    case IR::Opcode::BitwiseAnd32:
    case IR::Opcode::BitwiseOr32:
    case IR::Opcode::BitwiseXor32:
    case IR::Opcode::FPAdd32:
    case IR::Opcode::FPSub32:
    case IR::Opcode::FPMul32:
    case IR::Opcode::FPFma32:
    case IR::Opcode::FPAbs32:
    case IR::Opcode::FPNeg32:
    case IR::Opcode::FPMin32:
    case IR::Opcode::FPMax32:
    case IR::Opcode::FPSaturate32:
    case IR::Opcode::FPRecip32:
    case IR::Opcode::FPRecipSqrt32:
    case IR::Opcode::FPSqrt:
    case IR::Opcode::FPExp2:
    case IR::Opcode::FPLog2:
    case IR::Opcode::SelectU32:
    case IR::Opcode::SelectF32:
    case IR::Opcode::CompositeConstructF32x2:
    case IR::Opcode::CompositeConstructF32x3:
    case IR::Opcode::CompositeConstructF32x4:
    case IR::Opcode::CompositeExtractF32x2:
    case IR::Opcode::CompositeExtractF32x3:
    case IR::Opcode::CompositeExtractF32x4:
        return true;
    default:
        return false;
    }
}

bool IdenticalGraphicsExpression(const IR::Inst& a, const IR::Inst& b) {
    if (a.GetOpcode() != b.GetOpcode() ||
        a.Flags<u64>() != b.Flags<u64>() ||
        a.Definition<u32>() != b.Definition<u32>() ||
        a.NumArgs() != b.NumArgs()) {
        return false;
    }
    for (size_t i = 0; i < a.NumArgs(); ++i) {
        if (a.Arg(i) != b.Arg(i)) return false;
    }
    return true;
}

u32 GraphicsArithmeticCse(IR::Program& program) {
    u32 removed = 0;
    for (IR::Block* block : program.post_order_blocks) {
        // Each table is block-local, so every reused expression dominates the
        // later instruction, including inside divergent shader control flow.
        std::unordered_multimap<u64, IR::Inst*> seen;
        for (IR::Inst& inst : block->Instructions()) {
            if (!inst.HasUses() || !IsGraphicsPureArithmetic(inst.GetOpcode()) ||
                inst.MayHaveSideEffects()) {
                continue;
            }
            u64 key = HashCombine(u64{0}, static_cast<u64>(inst.GetOpcode()));
            key = HashCombine(key, inst.Flags<u64>());
            key = HashCombine(key, u64(inst.Definition<u32>()));
            for (size_t i = 0; i < inst.NumArgs(); ++i) {
                key = HashCombine(key, inst.Arg(i).Hash());
            }
            const auto [first, last] = seen.equal_range(key);
            IR::Inst* existing = nullptr;
            for (auto it = first; it != last; ++it) {
                if (IdenticalGraphicsExpression(inst, *it->second)) {
                    existing = it->second;
                    break;
                }
            }
            if (existing) {
                inst.ReplaceUsesWithAndRemove(IR::Value{existing});
                ++removed;
            } else {
                seen.emplace(key, &inst);
            }
        }
    }
    return removed;
}
} // namespace

IR::BlockList GenerateBlocks(const IR::AbstractSyntaxList& syntax_list) {
    size_t num_syntax_blocks{};
    for (const auto& [_, type] : syntax_list) {
        if (type == IR::AbstractSyntaxNode::Type::Block) {
            ++num_syntax_blocks;
        }
    }
    IR::BlockList blocks{};
    blocks.reserve(num_syntax_blocks);
    for (const auto& [data, type] : syntax_list) {
        if (type == IR::AbstractSyntaxNode::Type::Block) {
            blocks.push_back(data.block);
        }
    }
    return blocks;
}

void EmitControlFlowGraph(IR::Program& program, Pools& pools, Gcn::CFG& cfg,
                          RuntimeInfo& runtime_info, const Profile& profile) {
    Gcn::Translator translator{program.info, runtime_info, profile};
    for (auto& block : cfg) {
        const u32 start = block.begin_index;
        const u32 size = block.end_index - start + 1;
        auto* ir_block = pools.block_pool.Create(pools.inst_pool);
        ir_block->cfg_block = &block;
        block.ir_block = ir_block;
        translator.Translate(ir_block, block.begin, block.cond,
                             std::span{program.ins_list}.subspan(start, size));
        program.blocks.push_back(ir_block);
    }
    translator.EmitPrologue(program.blocks.front());
    ASSERT_MSG(!program.info.translation_failed, "Shader translation has failed");
    for (auto& block : cfg) {
        auto* ir_block = block.ir_block;
        if (block.branch_true) {
            auto* true_block = block.branch_true->ir_block;
            ir_block->AddBranch(true_block);
        }
        if (block.branch_false) {
            auto* false_block = block.branch_false->ir_block;
            ir_block->AddBranch(false_block);
        }
    }
    program.post_order_blocks = Shader::IR::PostOrder(program.blocks.front());
}

IR::Program TranslateProgram(const std::span<const u32>& code, Pools& pools, Info& info,
                             RuntimeInfo& runtime_info, const Profile& profile) {
    // Ensure first instruction is expected.
    constexpr u32 token_mov_vcchi = 0xBEEB03FF;
    if (code[0] != token_mov_vcchi) {
        LOG_WARNING(Render_Recompiler, "First instruction is not s_mov_b32 vcc_hi, #imm");
    }

    Gcn::GcnCodeSlice slice(code.data(), code.data() + code.size());
    Gcn::GcnDecodeContext decoder;

    // Decode and save instructions
    IR::Program program{info};
    program.ins_list.reserve(code.size());
    while (!slice.atEnd()) {
        program.ins_list.emplace_back(decoder.decodeInstruction(slice));
    }

    // Clear any previous pooled data.
    pools.ReleaseContents();

    // Create control flow graph
    Common::ObjectPool<Gcn::Block> gcn_block_pool{64};
    Gcn::CFG cfg{gcn_block_pool, program.ins_list};
    EmitControlFlowGraph(program, pools, cfg, runtime_info, profile);

    // On NVIDIA GPUs HW interpolation of clip distance values seems broken, and we need to emulate
    // it with expensive discard in PS.
    Shader::InjectClipDistanceAttributes(program, runtime_info);

    // Run optimization passes on unstructured graph
    if (!profile.support_float64) {
        Shader::Optimization::LowerFp64ToFp32(program);
    }
    Shader::Optimization::SsaRewritePass(program);
    Shader::Optimization::ConstantPropagationPass(program.post_order_blocks);
    if (info.sw_stage == SwStage::TessellationControl) {
        Shader::Optimization::TessellationPreprocess(program, runtime_info);
        Shader::Optimization::HullShaderTransform(program, runtime_info);
    } else if (info.sw_stage == SwStage::TessellationEval) {
        Shader::Optimization::TessellationPreprocess(program, runtime_info);
        Shader::Optimization::DomainShaderTransform(program, runtime_info);
    }
    Shader::Optimization::RingAccessElimination(program, runtime_info);
    Shader::Optimization::ReadLaneEliminationPass(program);
    Shader::IR::DumpProgram(program, info, "pre-res-discover.");
    auto resources = Shader::Optimization::ResourceDiscoverPass(program, profile);
    Shader::Optimization::FlattenExtendedUserdataPass(program);
    Shader::IR::DumpProgram(program, info, "pre-res-patch.");
    Shader::Optimization::ResourcePatchingPass(program.info, resources, profile);
    Shader::Optimization::LowerBufferFormatToRaw(program);
    Shader::Optimization::SharedMemorySimplifyPass(program, profile);
    Shader::Optimization::SharedMemoryToStoragePass(program, runtime_info, profile);
    Shader::Optimization::LowerUserClipPlanes(program, runtime_info);
    Shader::Optimization::PhiSimplificationPass(program);
    Shader::Optimization::InverseBallotEliminationPass(program);
    Shader::Optimization::LowerHardwareIntrinsics(program);
    Shader::IR::DumpProgram(program, info, "pre-lower-phi.");

    // Prepare for structurization by clearing flow graph and lowering phis
    for (auto* ir_block : program.blocks) {
        ir_block->imm_predecessors.clear();
        ir_block->imm_successors.clear();
        ir_block->ssa_state.Reset();
    }
    Shader::Optimization::LowerPhisToRegsPass(program);

    // Structurize control flow graph and create program.
    program.syntax_list = Shader::Gcn::BuildASL(pools, cfg, info);
    program.blocks = GenerateBlocks(program.syntax_list);
    program.post_order_blocks = Shader::IR::PostOrder(program.syntax_list.front().data.block);

    // Run optimization passes on structured graph
    Shader::Optimization::SsaRepairPass(program);
    Shader::Optimization::SsaRewritePass(program);
    Shader::Optimization::SharedMemoryBarrierPass(program, runtime_info, profile);
    Shader::Optimization::DeadCodeEliminationPass(program);
    Shader::Optimization::LowerWave64BallotPass(program, runtime_info, profile);
    Shader::Optimization::ConstantPropagationPass(program.post_order_blocks);
    Shader::Optimization::DeadCodeEliminationPass(program);
    const bool is_fragment = info.sw_stage == SwStage::Fragment;
    const bool graphics_cse = is_fragment ? profile.graphics_cse_fragment
                                         : info.sw_stage != SwStage::Compute &&
                                               profile.graphics_cse_vertex;
    if (graphics_cse) {
        const u32 eliminated = GraphicsArithmeticCse(program);
        if (eliminated) {
            Shader::Optimization::DeadCodeEliminationPass(program);
        }
        // Sample the first shaders only. The counter proves whether the new
        // instruction-elimination path actually fires on the player's game.
        static std::atomic<u32> samples_vertex{0}, samples_fragment{0};
        auto& counter = is_fragment ? samples_fragment : samples_vertex;
        if (counter.fetch_add(1, std::memory_order_relaxed) < 12) {
            std::printf("GPU IR CSE: %s shader %016llx removed %u repeated ALU instructions\n",
                        is_fragment ? "fragment" : "pre-raster",
                        static_cast<unsigned long long>(info.pgm_hash), eliminated);
        }
    }
    if (info.sw_stage == SwStage::Fragment && profile.needs_integer_interpolation_fix) {
        Shader::Optimization::InterpolatedIntegerPass(program);
    }
    Shader::Optimization::CollectShaderInfoPass(program, profile);
    Shader::IR::DumpProgram(program, info);

    return program;
}

} // namespace Shader
